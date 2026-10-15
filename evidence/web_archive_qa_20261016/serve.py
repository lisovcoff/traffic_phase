from pathlib import Path
import uvicorn
import tempfile
qa_temp=Path('evidence/web_archive_qa_20261016/runtime_temp').resolve()
qa_temp.mkdir(exist_ok=True)
tempfile.tempdir=str(qa_temp)
from app.main import app
import app.api.visualization as v
v.LOG_ROOT=Path('evidence/web_archive_qa_20261016/server_runs')
from fastapi.staticfiles import StaticFiles
app.mount('/qa',StaticFiles(directory='evidence'),name='qa')
uvicorn.run(app,host='127.0.0.1',port=8017)
