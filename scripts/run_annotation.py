"""Local annotation UI; bind to loopback, no model fitting."""
import argparse
import threading
import webbrowser
import json
from urllib.request import urlopen
from urllib.error import URLError
import uvicorn


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',type=int,default=8011)
    p.add_argument('--no-browser',action='store_true')
    args=p.parse_args()
    url=f'http://127.0.0.1:{args.port}/annotation'
    print('Traffic Phase annotation: '+url,flush=True)
    try:
        with urlopen(f'http://127.0.0.1:{args.port}/health',timeout=.5) as response:
            running=json.load(response)
        if running.get('mode')=='annotation_only':
            if not args.no_browser:webbrowser.open(url)
            print('Annotation server is already running.');return
    except (URLError,TimeoutError,ValueError):
        pass
    if not args.no_browser:
        timer=threading.Timer(1.5,lambda:webbrowser.open(url));timer.daemon=True;timer.start()
    uvicorn.run('app.annotation_app:app',host='127.0.0.1',port=args.port)


if __name__=='__main__':main()
