"""Run a persistent whole-intersection project in an isolated worker process."""
import argparse
from pathlib import Path
from app.core.intersection_project import run_project


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    model=run_project(args.input,args.output)
    print(model['model_id'],model['completeness'],len(model['sessions']),'sessions',len(model['regimes']),'regimes')


if __name__=='__main__':main()
