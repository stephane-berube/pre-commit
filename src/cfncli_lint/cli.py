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
            for cfncli_resource_name, cfncli_resource in stage.items():
                if cfncli_resource_name == 'Config':
                    continue

                packaged = False
                extends = cfncli_resource.get('Extends')

                if extends is not None:
                    blueprint = cfncli['Blueprints'][extends]

                    # Merge blueprint with cfncli_resource's properties
                    # blueprint properties also present in cfncli_resource will get
                    # overwritten by the cfncli_resource.
                    resource = blueprint | cfncli_resource
                else:
                    resource = cfncli_resource

                template = resource['Template']
                packaged = resource.get('Package', False)
                region = resource.get('Region', 'ca-central-1')

                template_path = Path(cfn_cli_dir + '/' + template).resolve()

                parameters = resource.get('Parameters', {})

                resources.append({
                    'Capabilities': resource.get('Capabilities', []),
                    'CfnCliPath': filename,
                    'Packaged': packaged,
                    'Parameters': parameters,
                    'Region': region,
                    'ResourceName': cfncli_resource_name,
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


def check_capabilities(cfn_cli_resource_name, capabilities, cfn_resources):
    error = False

    require_capabilities = [
        'AWS::IAM::Group',
        'AWS::IAM::AccessKey',
        'AWS::IAM::InstanceProfile',
        'AWS::IAM::ManagedPolicy',
        'AWS::IAM::Policy',
        'AWS::IAM::Role',
        'AWS::IAM::User',
        'AWS::IAM::UserToGroupAddition'
    ]

    for cfn_resource in cfn_resources.values():
        if cfn_resource['Type'] in require_capabilities and 'CAPABILITY_NAMED_IAM' not in capabilities:
            error = True
            logger.error(f'{cfn_cli_resource_name} is missing "CAPABILITY_NAMED_IAM" Capabilities')

    return error


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

        # Parse underlying template
        underlying_template = parse_underlying_template(resource['Template'])

        # cfn-lint checks
        results.append(run_cfn_lint(resource))

        # Check for missing params
        results.append(has_missing_params(resource, underlying_template['Parameters']))

        # Check for capabilities
        results.append(check_capabilities(resource['ResourceName'], resource['Capabilities'], underlying_template['Resources']))

    # Check for duplicate stack names
    results.append(has_duplicate_stack_names(stack_names))

    return results


def has_missing_params(resource: dict, template_parameters: dict) -> bool:
    """Checks if a cfn-cli resource has missing mandatory parameters.

    Args:
        resource (dict): Resource to perform checks on.
        template_parameters (dict): Parameters of the underlying template.

    Returns:
        bool: True if mandatory parameters are missing, False otherwise.
    """
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


def parse_underlying_template(template_path: str) -> dict:
    """Parse the underlying tempalte the cfn-cli resource points to.

    Args:
        template_path (str): Path of the CFN template file.

    Returns:
        dict: CFN template parameters.
    """
    with Path(template_path).open('r') as file:
        file_contents = file.read()

        return load_yaml(file_contents)


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
