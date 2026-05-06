import argparse
import collections
import yaml

from cfnlint.api import lint_file, ManualArgs
from .cfn_tools import load_yaml
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
                    'Parameters': parameters,
                    'Region': resource['Region'],
                    'ResourceName': resource_name,
                    'StackName': resource['StackName'],
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


def run_cfn_lint(resource: dict):
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
        parameters=[params],
        regions=['ca-central-1']
    )

    errors = lint_file(template_path, config)

    # TODO: stderr / logger
    for error in errors:
        print(f'{cfncli_path}:{resource_name} - [{error.rule.id}] {error.message}')

    return len(errors) > 0


# FIXME: Different regions are allowed to use the same stackname
def has_duplicate_stack_names(stack_names: list):
    duplicate_stack_names = [item for item, count in collections.Counter(stack_names).items() if count > 1]

    has_dupes = len(duplicate_stack_names) > 0

    # TODO: stderr / logger
    if has_dupes:
        print('Duplicate stack names:')

        for dupe in duplicate_stack_names:
            print('* ' + dupe)

    return has_dupes


def check_file(resources: list):
    results = []
    stack_names = []

    for resource in resources:
        stack_names.append(resource['StackName'])

        # cfn-lint checks
        results.append(run_cfn_lint(resource))

        # Check for missing params
        results.append(has_missing_params(resource))

    # Check for duplicate stack names
    results.append(has_duplicate_stack_names(stack_names))

    return results


def has_missing_params(resource: dict):
    template_parameters = get_template_parameters(resource['Template'])
    resource_parameter_names = resource['Parameters'].keys()
    resource_name = resource['ResourceName']

    missing_cfncli_parameters = []

    for name, value in template_parameters.items():
        if value.get('Default',  None) is None and name not in resource_parameter_names:
            missing_cfncli_parameters.append(name)

    has_missing_params = len(missing_cfncli_parameters) > 0

    if has_missing_params:
        print(f'Missing parameters for {resource_name}:')

        for missing_param in missing_cfncli_parameters:
            print(f'* {missing_param}')

    return has_missing_params


def get_template_parameters(template_path: str) -> dict:
    """Get parameters of the CFN template.

    Args:
        template_path (str): Path of the CFN template file.

    Returns:
        dict: CFN template parameters.
    """
    with Path(template_path).open('r') as file:
        file_contents = file.read()
        template = load_yaml(file_contents)

        return template.get('Parameters', {})


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
        results = check_file(target)

    return int(any(results))
