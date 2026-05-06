"""Validate cfn-cli.yaml templates before pushing to CodeCommit."""

import argparse
import collections
import logging
from collections.abc import Sequence
from pathlib import Path

import yaml
from cfnlint.api import ManualArgs, lint_file

from .cfn_tools import load_yaml

logger = logging.getLogger(__name__)

def parse_cfn_cli(filename: str) -> list:
    """Parse a cfn-cli.yaml file and return common properties.

    Args:
        filename (str): Path of the CFN template file.

    Returns:
        dict: Properties of the cfn-cli.yaml file.
    """
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


def find_cfn_cli_paths(filepaths: list) -> list:
    """Find the cfn-cli.yaml files about to be commited.

    Args:
        filepaths (list): List of file paths about to be commited.

    Returns:
        list: The paths to cfn-cli.yaml files about to be commited.
    """
    targets = []

    try:
        for filepath in filepaths:
            pth = Path(filepath)
            filename = pth.name    # ex: "cfn-cli.yaml"
            template_type = pth.parents[-2] # top-folder (ex: "foundational" or "products")

            if str(template_type) == 'products' and str(filename) == 'cfn-cli.yaml':
                targets.append(filepath)
    except Exception:
        logger.exception('Error while dealing with filepaths')

    return targets


def run_cfn_lint(resource: dict) -> bool:
    """Run cfn-lint checks.

    Runs on the underlying template with the parameters of the related
    resource from the cfn-cli.yaml file.

    Args:
        resource (list): Properties of the target resource in the cfn-cli.yaml file.

    Returns:
        bool: True if errors are found, False otherwise.
    """
    cfncli_path = resource['CfnCliPath']
    resource_name = resource['ResourceName']
    template_path = Path(resource['Template'])
    params = resource['Parameters']
    packaged = resource['Packaged']
    ignored_rules = []

    if packaged:
        ignored_rules.append('W3002')

    config = ManualArgs(
        ignore_checks=ignored_rules,
        parameters=[params],
        regions=['ca-central-1']
    )

    errors = lint_file(template_path, config)

    for error in errors:
        logger.error(f'{cfncli_path}:{resource_name} - [{error.rule.id}] {error.message}')

    return len(errors) > 0


def has_duplicate_stack_names(stack_names: list) -> bool:
    """Checks if a cfn-cli.yaml file contains duplicate stack names.

    The last resource would overwrite previous ones. So we want to flag this.

    Args:
        stack_names (list): List of stack names used in the cfn-cli file.

    Returns:
        bool: True if duplicates are found, False otherwise.
    """
    duplicate_stack_names = [item for item, count in collections.Counter(stack_names).items() if count > 1]

    has_dupes = len(duplicate_stack_names) > 0

    if has_dupes:
        logger.error('Duplicate stack names:')

        for dupe in duplicate_stack_names:
            logger.error('* ' + dupe)

    return has_dupes


def check_file(resources: list) -> list:
    """Perform a series of check on the given resources.

    Args:
        resources (list): Resource to perform checks on.

    Returns:
        list: Results of the various checks.
    """
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


def has_missing_params(resource: dict) -> bool:
    """Checks if a cfn-cli resource has missing mandatory parameters.

    Args:
        resource (dict): Resource to perform checks on.

    Returns:
        bool: True if mandatory parameters are missing, False otherwise.
    """
    template_parameters = get_template_parameters(resource['Template'])
    resource_parameter_names = resource['Parameters'].keys()
    resource_name = resource['ResourceName']

    missing_cfncli_parameters = []

    for name, value in template_parameters.items():
        if value.get('Default',  None) is None and name not in resource_parameter_names:
            missing_cfncli_parameters.append(name)

    has_missing_params = len(missing_cfncli_parameters) > 0

    if has_missing_params:
        logger.error(f'Missing parameters for {resource_name}:')

        for missing_param in missing_cfncli_parameters:
            logger.error(f'* {missing_param}')

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
    """The prek entrypoint.

    Args:
        argv (Sequence[str]): Files about to be commited, or None.

    Returns:
        int: 0 on success, any other number for failure.
    """
    parser = argparse.ArgumentParser(
        prog='cfncli-lint',
    )
    parser.add_argument(
        'filenames',
        nargs='+',
        help='Filenames to process.',
    )

    args = parser.parse_args(argv)
    cfn_cli_paths = find_cfn_cli_paths(args.filenames)

    results = []

    for cfn_cli_path in cfn_cli_paths:
        cfn_cli_info = parse_cfn_cli(cfn_cli_path)
        results = check_file(cfn_cli_info)

    return int(any(results))
