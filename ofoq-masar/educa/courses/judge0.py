"""Bounded Judge0 CE 1.13.1 transport. No database, student options, or POST retries."""
import base64
import binascii
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import http.client
import json
import math
import re
import socket
import ssl
import uuid
from urllib.parse import urlsplit, urlencode

from django.conf import settings

from .lab_policy import resource_limits


MESSAGES = {
    'not_configured': 'لم تُضبط خدمة Judge0 لهذا المحرك',
    'configuration_error': 'إعداد اتصال Judge0 غير صالح',
    'connection_failed': 'تعذّر الاتصال بخدمة التنفيذ',
    'creation_uncertain': 'قد تكون الخدمة قبلت العملية؛ لن يُعاد إرسالها تلقائيًا',
    'timeout': 'انتهت مهلة قراءة خدمة التنفيذ',
    'authentication_rejected': 'رفضت خدمة التنفيذ مصادقة الخادم',
    'request_rejected': 'رفضت خدمة التنفيذ الطلب',
    'service_failed': 'خدمة التنفيذ غير متاحة حاليًا',
    'protocol_error': 'استجابة خدمة التنفيذ غير صالحة',
    'response_too_large': 'تجاوزت استجابة خدمة التنفيذ الحجم المسموح',
    'unsupported_version': 'إصدار خدمة التنفيذ غير مدعوم بهذا الموصل',
    'unsafe_service': 'إعدادات عزل خدمة التنفيذ لم تجتز الفحص',
    'invalid_input': 'بيانات التنفيذ أو الحدود غير صالحة',
    'language_changed': 'تعريف اللغة لا يطابق الخدمة الحالية',
}


class Judge0Error(Exception):
    def __init__(self, code, *, uncertain=False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(MESSAGES[code])

    def public_data(self):
        return {'code': self.code, 'message': str(self), 'creation_uncertain': self.uncertain}


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), default=str).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class ConnectionConfig:
    engine_key: str
    base_url: str = field(repr=False)
    auth_token: str = field(default='', repr=False)
    auth_header: str = 'X-Auth-Token'
    connect_timeout: float = 3
    read_timeout: float = 5
    max_response_bytes: int = 4194304
    max_input_bytes: int = 65536
    max_source_bytes: int = 400000
    wall_seconds: int = 30
    processes: int = 32
    allow_http: bool = False
    dedicated: bool = False
    sandbox_review_id: str = ''
    expected_version: str = '1.13.1'

    @classmethod
    def from_settings(cls, key):
        rows = getattr(settings, 'LAB_JUDGE0_SERVICES', {})
        if not isinstance(rows, dict) or key not in rows:
            raise Judge0Error('not_configured')
        row = rows[key]
        allowed = set(cls.__dataclass_fields__) - {'engine_key'}
        if not isinstance(row, dict) or set(row) - allowed:
            raise Judge0Error('configuration_error')
        try:
            config = cls(engine_key=key, **row)
            config.validate()
            return config
        except (TypeError, ValueError):
            raise Judge0Error('configuration_error') from None

    def validate(self):
        url = urlsplit(self.base_url)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
                or url.query or url.fragment or any(c in self.base_url for c in '\r\n')
                or (url.scheme == 'http' and not self.allow_http)
                or url.hostname.lower() in ('ce.judge0.com', 'api.judge0.com', 'extra-ce.judge0.com')):
            raise ValueError
        _ = url.port
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', self.engine_key):
            raise ValueError
        if not re.fullmatch(r'X-[A-Za-z0-9-]{1,60}', self.auth_header) or any(c in self.auth_token for c in '\r\n'):
            raise ValueError
        if self.expected_version != '1.13.1':
            raise Judge0Error('unsupported_version')
        for value in (self.connect_timeout, self.read_timeout):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 30:
                raise ValueError
        for value, cap in [(self.max_response_bytes, 16777216), (self.max_input_bytes, 1048576),
                           (self.max_source_bytes, 1048576), (self.wall_seconds, 30), (self.processes, 64)]:
            if type(value) is not int or not 0 < value <= cap:
                raise ValueError
        if type(self.allow_http) is not bool or type(self.dedicated) is not bool or not isinstance(self.sandbox_review_id, str):
            raise ValueError

    def profile(self):
        # Credentials are deliberately excluded; endpoint identity is included only as a hash.
        return {'adapter': 'judge0-ce-1.13.1-v1', 'engine_key': self.engine_key,
            'endpoint_hash': digest(self.base_url.rstrip('/')), 'expected_version': self.expected_version,
            'wall_seconds': self.wall_seconds, 'processes': self.processes,
            'max_response_bytes': self.max_response_bytes, 'max_input_bytes': self.max_input_bytes,
            'max_source_bytes': self.max_source_bytes, 'dedicated': self.dedicated,
            'sandbox_review_id': self.sandbox_review_id, 'allow_http': self.allow_http}


def execution_profile_hash(engine):
    rows = getattr(settings, 'LAB_JUDGE0_SERVICES', {})
    if engine.key not in rows:
        return ''  # Legacy isolated data fixtures; never authorizes transport.
    return digest({'connection': ConnectionConfig.from_settings(engine.key).profile(),
                   'capabilities_hash': engine.capabilities_hash})


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


class HTTPTransport:
    def __init__(self, config):
        self.config = config

    def request(self, method, path, payload=None):
        config = self.config
        url = urlsplit(config.base_url)
        connection = None
        sending = False
        try:
            cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
            extra = {'context': ssl.create_default_context()} if url.scheme == 'https' else {}
            connection = cls(url.hostname, url.port, timeout=config.connect_timeout, **extra)
            connection.connect()
            connection.sock.settimeout(config.read_timeout)
            headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity', 'Content-Type': 'application/json'}
            if config.auth_token:
                headers[config.auth_header] = config.auth_token
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8') if payload is not None else None
            sending = method == 'POST'
            connection.request(method, url.path.rstrip('/') + path, body=body, headers=headers)
            response = connection.getresponse()
            status = response.status
            if status in (401, 403):
                raise Judge0Error('authentication_rejected')
            if status in (400, 404, 413, 422, 429):
                raise Judge0Error('request_rejected')
            if status not in (200, 201):
                raise Judge0Error('creation_uncertain' if sending else 'service_failed', uncertain=sending)
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise Judge0Error('protocol_error', uncertain=sending)
            if response.getheader('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                raise Judge0Error('protocol_error', uncertain=sending)
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdecimal() or int(length) > config.max_response_bytes):
                raise Judge0Error('response_too_large', uncertain=sending)
            data = response.read(config.max_response_bytes + 1)
            if len(data) > config.max_response_bytes:
                raise Judge0Error('response_too_large', uncertain=sending)
            return json.loads(data.decode('utf-8'), object_pairs_hook=_pairs,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
        except Judge0Error:
            raise
        except (socket.timeout, TimeoutError):
            raise Judge0Error('creation_uncertain' if sending else 'timeout', uncertain=sending) from None
        except (UnicodeError, ValueError, http.client.HTTPException):
            raise Judge0Error('protocol_error', uncertain=sending) from None
        except (OSError, ssl.SSLError):
            raise Judge0Error('creation_uncertain' if sending else 'connection_failed', uncertain=sending) from None
        finally:
            if connection is not None:
                connection.close()


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    verdict: str | None
    stdout: str = field(default='', repr=False)
    stderr: str = field(default='', repr=False)
    compile_output: str = field(default='', repr=False)
    message: str = field(default='', repr=False)
    cpu_time: str | None = None
    memory_kb: int | None = None

    def public_data(self):
        # No token, code, test input/expected output, compiler text, or service message.
        return {'status': self.status, 'verdict': self.verdict,
                'cpu_time': self.cpu_time, 'memory_kb': self.memory_kb}

    def private_data(self):
        return {**self.public_data(), 'stdout': self.stdout, 'stderr': self.stderr,
                'compile_output': self.compile_output, 'message': self.message}


STATUSES = {1: ('queued', None), 2: ('running', None), 3: ('finished', 'accepted'),
    4: ('finished', 'wrong_answer'), 5: ('finished', 'time_limit'), 6: ('finished', 'compile_error'),
    7: ('finished', 'runtime_error'), 8: ('finished', 'output_limit'),
    9: ('finished', 'runtime_error'), 10: ('finished', 'runtime_error'),
    11: ('finished', 'runtime_error'), 12: ('finished', 'runtime_error'),
    13: ('failed', 'system_error'), 14: ('finished', 'runtime_error')}


class Judge0Client:
    def __init__(self, engine_key, *, transport=None):
        self.config = ConnectionConfig.from_settings(engine_key)
        self.transport = transport or HTTPTransport(self.config)
        self._probe = None

    def probe(self):
        about = self.transport.request('GET', '/about')
        if not isinstance(about, dict) or about.get('version') != self.config.expected_version:
            raise Judge0Error('unsupported_version')
        config = self.transport.request('GET', '/config_info')
        if not isinstance(config, dict):
            raise Judge0Error('protocol_error')
        keys = ('enable_network', 'allow_enable_network', 'max_cpu_time_limit', 'max_wall_time_limit',
                'max_memory_limit', 'max_max_file_size', 'max_max_processes_and_or_threads')
        observed = {key: config.get(key) for key in keys}
        self._probe = {'version': about['version'], 'config': observed,
                       'capabilities_hash': digest({'version': about['version'], 'config': observed})}
        return self._probe

    def _safe_service(self):
        info = self._probe or self.probe()
        config = info['config']
        if not self.config.dedicated or not self.config.sandbox_review_id:
            raise Judge0Error('unsafe_service')
        if config['enable_network'] is not False or config['allow_enable_network'] is not False:
            raise Judge0Error('unsafe_service')
        ceilings = {'max_cpu_time_limit': 10, 'max_wall_time_limit': self.config.wall_seconds,
            'max_memory_limit': 524288, 'max_max_file_size': 1024, 'max_max_processes_and_or_threads': 64}
        for key, ceiling in ceilings.items():
            value = config.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= ceiling:
                raise Judge0Error('unsafe_service')
        if config['max_max_processes_and_or_threads'] < self.config.processes:
            raise Judge0Error('unsafe_service')
        return info

    def languages(self):
        data = self.transport.request('GET', '/languages')
        if not isinstance(data, list):
            raise Judge0Error('protocol_error')
        seen = set()
        rows = []
        for row in data:
            if (not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] < 1
                    or row['id'] in seen or not isinstance(row.get('name'), str)
                    or not row['name'].strip() or len(row['name']) > 250):
                raise Judge0Error('protocol_error')
            seen.add(row['id'])
            rows.append({'id': row['id'], 'name': row['name']})
        return rows

    def assert_language(self, language_snapshot):
        if not isinstance(language_snapshot, dict) or language_snapshot.get('engine_key') != self.config.engine_key:
            raise Judge0Error('invalid_input')
        found = next((row for row in self.languages() if row['id'] == language_snapshot.get('judge0_language_id')), None)
        if not found or not language_snapshot.get('remote_name') or found['name'] != language_snapshot['remote_name']:
            raise Judge0Error('language_changed')

    def submit(self, *, source_code, stdin, language_snapshot, cpu_seconds, memory_kb, output_bytes):
        info = self._safe_service()
        limits = resource_limits()
        try:
            cpu = Decimal(str(cpu_seconds))
            if not cpu.is_finite() or cpu != cpu.quantize(Decimal('.01')) or not 0 < cpu <= limits['max_cpu_seconds']:
                raise ValueError
            if type(memory_kb) is not int or not 0 < memory_kb <= limits['max_memory_kb']:
                raise ValueError
            if type(output_bytes) is not int or not 0 < output_bytes <= limits['max_output_bytes']:
                raise ValueError
            if not isinstance(source_code, str) or not source_code or len(source_code.encode('utf-8')) > self.config.max_source_bytes:
                raise ValueError
            if not isinstance(stdin, str) or len(stdin.encode('utf-8')) > self.config.max_input_bytes:
                raise ValueError
            wall = min(self.config.wall_seconds, float(cpu) * 2 + 2)
            # Whole-KiB backend file limit is only a coarse bound, not stdout-byte enforcement.
            file_kb = max(1, math.ceil(output_bytes / 1024))
            remote = info['config']
            if (float(cpu) > remote['max_cpu_time_limit'] or wall > remote['max_wall_time_limit']
                    or memory_kb > remote['max_memory_limit'] or file_kb > remote['max_max_file_size']):
                raise ValueError
        except (ValueError, TypeError, UnicodeError, InvalidOperation):
            raise Judge0Error('invalid_input') from None
        self.assert_language(language_snapshot)
        body = {'source_code': base64.b64encode(source_code.encode('utf-8')).decode('ascii'),
            'stdin': base64.b64encode(stdin.encode('utf-8')).decode('ascii'),
            'language_id': language_snapshot['judge0_language_id'],
            'cpu_time_limit': float(cpu), 'cpu_extra_time': 0, 'wall_time_limit': wall,
            'memory_limit': memory_kb, 'stack_limit': min(memory_kb, 65536),
            'max_file_size': file_kb, 'max_processes_and_or_threads': self.config.processes,
            'enable_per_process_and_thread_time_limit': False,
            'enable_per_process_and_thread_memory_limit': False,
            'enable_network': False, 'redirect_stderr_to_stdout': False, 'number_of_runs': 1}
        data = self.transport.request('POST', '/submissions?base64_encoded=true&wait=false', body)
        try:
            token = str(uuid.UUID(data['token']))
            if not isinstance(data['token'], str):
                raise ValueError
            return token
        except (ValueError, TypeError, KeyError, AttributeError):
            raise Judge0Error('creation_uncertain', uncertain=True) from None

    def result(self, token, *, output_bytes, memory_kb):
        try:
            canonical = str(uuid.UUID(token))
            if canonical != token or type(output_bytes) is not int or not 0 < output_bytes <= 1048576 or type(memory_kb) is not int or memory_kb < 1:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise Judge0Error('invalid_input') from None
        fields = 'token,status,stdout,stderr,compile_output,message,time,memory,exit_code'
        data = self.transport.request('GET', '/submissions/' + canonical + '?' + urlencode({'base64_encoded': 'true', 'fields': fields}))
        try:
            if not isinstance(data, dict) or data.get('token') != token:
                raise ValueError
            status_id = data['status']['id']
            if type(status_id) is not int or status_id not in STATUSES:
                raise ValueError
            status, verdict = STATUSES[status_id]
            cpu, memory = data.get('time'), data.get('memory')
            if cpu is not None:
                number = Decimal(str(cpu))
                if not number.is_finite() or number < 0:
                    raise ValueError
                cpu = str(number)
            if memory is not None and (type(memory) is not int or memory < 0):
                raise ValueError
            decoded, total = {}, 0
            for key in ('stdout', 'stderr', 'compile_output', 'message'):
                text = data.get(key) or ''
                if not isinstance(text, str):
                    raise ValueError
                if len(text) > 4 * math.ceil(output_bytes / 3) + 2048:
                    return ExecutionResult('finished', 'output_limit', cpu_time=cpu, memory_kb=memory)
                raw = base64.b64decode(''.join(text.split()), validate=True)
                total += len(raw)
                if total > output_bytes:
                    return ExecutionResult('finished', 'output_limit', cpu_time=cpu, memory_kb=memory)
                try:
                    decoded[key] = raw.decode('utf-8')
                except UnicodeDecodeError:
                    return ExecutionResult('finished', 'runtime_error', cpu_time=cpu, memory_kb=memory)
            if status == 'finished' and memory is not None and memory > memory_kb:
                verdict = 'memory_limit'
            return ExecutionResult(status, verdict, cpu_time=cpu, memory_kb=memory, **decoded)
        except (ValueError, KeyError, TypeError, InvalidOperation, binascii.Error):
            raise Judge0Error('protocol_error') from None
