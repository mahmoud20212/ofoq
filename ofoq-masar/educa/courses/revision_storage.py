from django.conf import settings
from django.core.files.storage import FileSystemStorage
from pathlib import Path


class RevisionStorage(FileSystemStorage):
    @property
    def base_location(self):
        return getattr(settings, 'REVISION_MEDIA_ROOT', settings.BASE_DIR / 'private-revisions')

    @property
    def location(self):
        return str(Path(self.base_location).resolve())


def revision_storage():
    # Draft assets are outside MEDIA_ROOT and are served only after authorization.
    return RevisionStorage(base_url='/teachers/assets/')
