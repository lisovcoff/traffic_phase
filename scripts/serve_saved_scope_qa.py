"""Local QA only: replay one sealed synthetic prediction instead of fitting."""
from copy import deepcopy
import json
from pathlib import Path

import uvicorn
from app.main import app
from app.core.v9 import model
from app.core.v9.source_scope import input_sessions


def main():
    folder = Path(__file__).resolve().parents[1]/'evidence/archive_session_isolation_20261016'
    prediction = json.loads((folder/'selected_prediction.json').read_text(encoding='utf-8'))
    expected = prediction['input_scope']['selected_session']['session_id']

    def saved_only(bundle, **kwargs):
        sessions = input_sessions(bundle, 'b.json')
        if len(sessions) != 1 or sessions[0].metadata['session_id'] != expected:
            raise ValueError('QA_REPLAY_INPUT_DIFFERS_FROM_SEALED_SELECTED_SESSION')
        print('[QA_SAVED_PREDICTION_REPLAY] no phase fitting', flush=True)
        return deepcopy(prediction)

    model._discover_bundle = saved_only
    uvicorn.run(app, host='127.0.0.1', port=8019)


if __name__ == '__main__':
    main()
