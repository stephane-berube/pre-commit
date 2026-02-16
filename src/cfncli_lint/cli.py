import subprocess
import yaml
from pathlib import Path
import argparse
from typing import Sequence


def parse_cfn_cli(filename):
    resources = []
    cfn_cli_pth = Path(filename)
    cfn_cli_dir = str(cfn_cli_pth.parent)

    with cfn_cli_pth.open('r') as file:
        cfncli = yaml.load(file, Loader=yaml.Loader)

        for stage in cfncli['Stages'].values():
            for resource_name, resource in stage.items():
                if resource_name == 'Config':
                    continue

                template = Path(cfn_cli_dir + '/' + resource['Template']).resolve()
                params = []

                for key, value in resource.get('Parameters', {}).items():
                    params.append(f'{key}={value}')
                
                resources.append({
                    'CfnCliPath': filename,
                    'Template': str(template),
                    'Parameters': params
                })

    return resources


def find_targets(filepaths: list) -> list:
    targets = []

    for filepath in filepaths:
        pth = Path(filepath)
        filename = pth.name    # ex: "cfn-cli.yaml"
        type = pth.parents[-2] # top-folder (ex: "foundational" or "products")

        if str(type) == 'products' and str(filename) == 'cfn-cli.yaml':
            cfn_cli_info = parse_cfn_cli(filepath)

            targets.append(cfn_cli_info)

    # TODO: if name is another yaml (presumably an underlying template)
        # Add to cfn-cli target as long as it wasn't part of a cfn-cli
        # We'll run cfn-cli without parameters on those ones.

    # TODO: if the .yaml file is in /foundational
        # TODO: cfn-lint with its equivalent .json

    return targets


def run_cfn_lint(resources: list):
    results = []

    for resource in resources:
        template_path = resource['Template']
        params = resource['Parameters']
        cfncli_path = resource['CfnCliPath']

        try:
            result = subprocess.run(
                ["cfn-lint", '--template', template_path, "--parameters"] + params,
                capture_output=True, # Captures stdout and stderr
                text=True,           # Decodes output as a string (instead of bytes)
                check=True           # Raises CalledProcessError if it fails
            )
            print(result.stdout)
            failure = False
        except subprocess.CalledProcessError as e:
            print(cfncli_path)
            lines = e.stdout.splitlines()

            for line in lines:
                if line != "":
                    print(f'    * {line}')

            print(e.stderr)

            failure = True

        results.append(failure)

    return results


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='cfncli-lint',
    )
    parser.add_argument(
        'filenames',
        nargs='+',
        help='Filenames to process.',
    )

    args = parser.parse_args(argv)
    targets = find_targets(args.filenames)

    results = []

    for target in targets:
        results.extend(run_cfn_lint(target))

    return int(any(results))
