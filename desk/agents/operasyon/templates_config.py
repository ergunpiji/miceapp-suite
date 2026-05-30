"""
Paylaşılan Jinja2Templates örneği.
Tüm router'lar buradan import eder — filtreler ve global'ler tek yerden yönetilir.
"""
import json
import os
from fastapi.templating import Jinja2Templates

_BASE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(_BASE, "templates"))
# Sub-app olarak mount edilince OA_URL_PREFIX="/operasyon" set edilir.
templates.env.globals["base_url"] = os.getenv("OA_URL_PREFIX", "")


def _from_json(s):
    if not s:
        return []
    try:
        result = json.loads(s)
        return result if isinstance(result, list) else []
    except Exception:
        return []


templates.env.filters["from_json"] = _from_json
