"""Google Drive: ссылка на папку, последние файлы, перезалив master.

Бот venv не содержит google-api/openpyxl — поэтому операции с Drive выполняем
в venv парсера через subprocess (там стоят все зависимости и лежит utils.gdrive).
Ссылку на папку формируем локально из GDRIVE_FOLDER_ID (.env парсера).
"""
import asyncio
import json
import os

from dotenv import load_dotenv

PARSER_DIR = os.getenv("PARSER_DIR", "/home/ritual_parser")
PARSER_PY = os.path.join(PARSER_DIR, "venv", "bin", "python")
load_dotenv(os.path.join(PARSER_DIR, ".env"))


def _folder_id() -> str:
    return os.getenv("GDRIVE_FOLDER_ID", "")


def folder_link() -> str:
    fid = _folder_id()
    return f"https://drive.google.com/drive/folders/{fid}" if fid else ""


async def _parser_py(code: str, timeout: float) -> tuple[int, str]:
    """Выполнить python-код в venv парсера (cwd=PARSER_DIR, .env подхватится)."""
    proc = await asyncio.create_subprocess_exec(
        PARSER_PY, "-c", code, cwd=PARSER_DIR,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, f"timeout after {timeout}s"
    return proc.returncode, (out or b"").decode("utf-8", errors="replace")


_LIST_CODE = (
    "import json, os\n"
    "from dotenv import load_dotenv; load_dotenv()\n"
    "from utils.gdrive import _get_service\n"
    "fid=os.getenv('GDRIVE_FOLDER_ID','')\n"
    "s=_get_service()\n"
    "r=s.files().list(q=f\"'{fid}' in parents and trashed=false\","
    "fields='files(name,modifiedTime,size)',orderBy='modifiedTime desc').execute()\n"
    "print('JSON:'+json.dumps(r.get('files',[])[:5]))\n"
)

_REUP_CODE = (
    "import os\n"
    "from dotenv import load_dotenv; load_dotenv()\n"
    "from utils.merger import build_master_xlsx\n"
    "from utils.gdrive import upload_file\n"
    "c,x=build_master_xlsx()\n"
    "ok=[]\n"
    "if c and os.path.exists(c) and upload_file(c): ok.append('master_all.csv')\n"
    "if x and os.path.exists(x) and upload_file(x): ok.append('master_all.xlsx')\n"
    "print('RESULT:'+(','.join(ok) if ok else 'FAIL'))\n"
)


async def get_drive_text() -> str:
    link = folder_link()
    if not link:
        return "GDRIVE_FOLDER_ID не задан в .env парсера."
    lines = ["☁ <b>Google Drive</b>", f'<a href="{link}">Открыть папку</a>', ""]
    code, out = await _parser_py(_LIST_CODE, timeout=40)
    files: list[dict] = []
    for line in out.splitlines():
        if line.startswith("JSON:"):
            try:
                files = json.loads(line[5:])
            except Exception:
                pass
    if files:
        lines.append("<b>Последние файлы:</b>")
        for f in files:
            mt = (f.get("modifiedTime", "") or "")[:16].replace("T", " ")
            sz = f.get("size")
            szs = f"{int(sz) / 1024:.0f} KB" if sz and str(sz).isdigit() else ""
            lines.append(f"  {f.get('name')} — {mt} {szs}".rstrip())
    elif code != 0:
        lines.append(f"<i>не удалось прочитать список файлов (rc={code})</i>")
    return "\n".join(lines)


async def reupload_master() -> str:
    if not _folder_id():
        return "GDRIVE_FOLDER_ID не задан — заливать некуда."
    code, out = await _parser_py(_REUP_CODE, timeout=240)
    for line in out.splitlines():
        if line.startswith("RESULT:"):
            res = line[7:]
            return f"✅ Залито: {res}" if res != "FAIL" else "❌ Не удалось залить."
    return f"❌ Ошибка перезалива (rc={code}):\n{out[-500:]}"
