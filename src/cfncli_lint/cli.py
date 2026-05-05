import argparse
import yaml

from cfnlint.api import lint_file, ManualArgs
from pathlib import Path
from typing import Sequence


# TODO: handle nested stacks
#       When a resource type is "AWS::CloudFormation::Stack"
#       Add the underlying template as a resource and pass params, etc.

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

                packaged = False
                extends = resource.get('Extends')

                if extends is not None:
                    blueprint = cfncli['Blueprints'][extends]
                    template = blueprint['Template']
                    packaged = blueprint.get('Package', False)
                else:
                    template = resource['Template']
                    packaged = resource.get('Package', False)

                template_path = Path(cfn_cli_dir + '/' + template).resolve()

                parameters = resource.get('Parameters', {})

                resources.append({
                    'CfnCliPath': filename,
                    'Packaged': packaged,
                    'Parameters': [parameters],
                    'ResourceName': resource_name,
                    'Template': str(template_path)
                })

    return resources


def find_targets(filepaths: list) -> list:
    targets = []

    try:
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
    except Exception as e:
        print(e)

    return targets


def run_cfn_lint(resources: list):
    results = []

    for resource in resources:
        cfncli_path = resource['CfnCliPath']
        resource_name = resource['ResourceName']
        template_path = Path(resource['Template'])
        params = resource['Parameters']
        packaged = resource['Packaged']
        ignored_rules = []

        if packaged:
            ignored_rules.append('W3002')

        # TODO: look into the feasibility of using our config file
        #       and then tweaking it to add rules, params, etc.
        # config = ConfigFileArgs()
        config = ManualArgs(
            ignore_checks=ignored_rules,
            parameters=params,
            regions=['ca-central-1']
        )

        errors = lint_file(template_path, config)

        for error in errors:
            print(f'{cfncli_path}:{resource_name} - [{error.rule.id}] {error.message}')

        failure = False
        if len(errors) > 0:
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

main()
