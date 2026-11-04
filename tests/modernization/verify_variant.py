"""Select exact dependency expectations before invoking the existing runner.

The verifier supplies the variant explicitly. This adapter does not infer it
from installed packages or repository contents, and never installs dependencies.
The existing runner remains responsible for discovery, reports and exit status.
DISPLAY and all other unrelated environment values remain inherited.
"""

import argparse
import os
from pathlib import Path
import runpy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variant', choices=('baseline', 'candidate'))
    args = parser.parse_args()
    variables = ('MODERNIZE_VERIFICATION_VARIANT', 'TRANSCRIPT_ACCEPTANCE_VARIANT')
    previous = {variable: os.environ.get(variable) for variable in variables}
    for variable in variables:
        os.environ[variable] = args.variant
    try:
        runpy.run_path(str(Path(__file__).with_name('run.py')), run_name='__main__')
    finally:
        for variable, value in previous.items():
            if value is None:
                os.environ.pop(variable, None)
            else:
                os.environ[variable] = value


if __name__ == '__main__':
    main()
