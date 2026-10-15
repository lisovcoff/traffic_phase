"""Small standalone review application; production inference is never invoked."""
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from app.api.annotation import router

app=FastAPI(title='Traffic Phase — ручная проверка',version='1.0')
app.include_router(router)


@app.get('/')
def root():return RedirectResponse('/annotation')


@app.get('/health')
def health():return {'status':'ok','mode':'annotation_only','inference':False}
