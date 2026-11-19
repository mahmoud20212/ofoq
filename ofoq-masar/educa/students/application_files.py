from pathlib import Path
from uuid import uuid4
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible


@deconstructible
class ApplicationStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=getattr(settings, 'TEACHER_APPLICATION_ROOT', settings.BASE_DIR / 'private-applications'), base_url=None)

    def url(self, name):
        raise ValueError('Private documents have no public URL')


def cv_path(instance, filename):
    return f'{uuid4().hex}{Path(filename).suffix.lower()}'


def validate_cv(upload):
    if not upload.size or upload.size > 5 * 1024 * 1024:
        raise ValidationError('يجب ألا يتجاوز حجم السيرة الذاتية 5 ميغابايت.')
    extension = Path(upload.name).suffix.lower()
    if extension not in ('.pdf', '.docx'):
        raise ValidationError('ارفع السيرة الذاتية بصيغة PDF أو DOCX.')
    try:
        data = upload.read()
        if extension == '.pdf':
            from pypdf import PdfReader
            if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-1024:]:
                raise ValueError('Invalid PDF')
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted or not len(reader.pages):
                raise ValueError('Encrypted or empty PDF')
            for page in reader.pages:
                page.get('/MediaBox')
        else:
            with ZipFile(BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 2000 or sum(e.file_size for e in entries) > 25 * 1024 * 1024:
                    raise ValueError('Oversized document')
                if any(e.flag_bits & 1 for e in entries) or archive.testzip():
                    raise ValueError('Corrupt document')
                if any(e.filename.lower().endswith('vbaproject.bin') for e in entries):
                    raise ValueError('Macro document')
                relationships = ElementTree.fromstring(archive.read('_rels/.rels'))
                if not any(e.get('Target') in ('word/document.xml', '/word/document.xml') and e.get('Type', '').endswith('/officeDocument') for e in relationships):
                    raise ValueError('Missing document relationship')
                types = ElementTree.fromstring(archive.read('[Content_Types].xml'))
                expected = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
                if not any(e.get('PartName') == '/word/document.xml' and e.get('ContentType') == expected for e in types):
                    raise ValueError('Not a Word document')
                document = ElementTree.fromstring(archive.read('word/document.xml'))
                if document.tag != '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document':
                    raise ValueError('Invalid Word document')
    except Exception as exc:
        raise ValidationError('ملف السيرة الذاتية تالف أو غير مدعوم. ارفع ملف PDF أو DOCX صالحًا وغير محمي بكلمة مرور.') from exc
    finally:
        upload.seek(0)
