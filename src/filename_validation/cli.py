import yaml
from pathlib import Path
import argparse
from typing import Sequence


def is_valid_filename(filename: str, min_len: int = 3) -> bool:
    name = Path(filename).stem

    if too_short := len(name) < min_len:
        print(f'Name too short ({min_len=}): {filename}')

    failure = too_short
    return not failure


def parse_cfn_cli(filename):
    resources = []

    with Path(filename).open('r') as file:
        cfncli = yaml.load_safe(file, Loader=yaml.Loader)

        for stage in cfncli['Stages']:
            for resource_name, resource in stage.items():
                if resource_name == 'Config':
                    continue

                template = Path(resource['Template']).resolve()
                params = []

                for key, value in resource.get('Parameters', {}):
                    params.append(f'{key}={value}')
                
                resources.append({
                    'Template:': template,
                    'Parameters': params
                })

    return resources


def find_targets(filepaths: list) -> list:
    print('filepaths:')
    print(filepaths)

    for filepath in filepaths:
        pth = Path(filepath)
        filename = pth.name    # ex: "cfn-cli.yaml"
        type = pth.parents[-1] # top-folder (ex: "foundational" or "products")

        if type == 'products' and filename == 'cfn-cli.yaml':
            cfn_cli_info = parse_cfn_cli(filename)

            print(cfn_cli_info)

    # name = Path(filename).stem
    # TODO: if the .yaml file is in /products
        # TODO: if name is cfn-cli, get parameters, get underlying template
        # TODO: if name is another yaml (presumably an underlying template)
            # Add to cfn-cli target as long as it wasn't part of a cfn-cli
            # We'll run cfn-cli without parameters on those ones.
    # TODO: if the .yaml file is in /foundational
        # TODO: cfn-lint with its equivalent .json

    return []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='validate-filename',
    )
    parser.add_argument(
        'filenames',
        nargs='+',
        help='Filenames to process.',
    )
    parser.add_argument(
        '--min-len',
        default=3,
        type=int,
        help='Minimum length for a filename.',
    )

    print('uhhh...')
    args = parser.parse_args(argv)
    targets = find_targets(args.filenames)

    results = [
        not is_valid_filename(filename, args.min_len)
        for filename in args.filenames
    ]

    return int(any(results))
