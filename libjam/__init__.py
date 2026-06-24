"""A Python library that makes it easier to create better CLIs and provides some missing pieces for file management.

Source: https://github.com/philippkosarev/libjam
Docs: https://libjam.readthedocs.io
PyPi: https://pypi.org/project/libjam
"""

from .captain import Captain, captain
from .secretary import Secretary, File
from . import writer
from . import flashcard
from . import drawer
from .path import Path
