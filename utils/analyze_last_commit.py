# Copyright (c) EGOGE - All Rights Reserved.
# This software may be used and distributed according to the terms of the GPL-3.0 license.
import subprocess
import re
from typing import Dict, List, Tuple, Optional

ChangeDetail = Tuple[str, str, bool]
FileChanges = Dict[str, List[ChangeDetail]]

def get_git_commit_diff(repo_path: Optional[str]) -> FileChanges:
    diff = get_last_commit_diff(repo_path=repo_path)
    if diff:
        return parse_git_diff(diff)
    else:
        return None

def get_last_commit_diff(repo_path: Optional[str]):
    """
    Retrieves the last commit changes that are relevant to translation files from a specified local git repository path.
    
    Args:
    repo_path (str): The file system path to the local git repository.
    
    Returns:
    List[str]: A list of file paths that changed in the last commit and match the '_en_US.properties' pattern.
    """
    try:
        if repo_path is None: 
            return subprocess.check_output(
                ['git', 'diff', 'HEAD~1', 'HEAD'], 
                text=True
            )
        else:    
            return subprocess.check_output(
                ['git', 'diff', 'HEAD~1', 'HEAD'], 
                text=True,
                cwd=repo_path
            )
    except subprocess.CalledProcessError as e:
        print("Failed to get commit diff:", e)
        return None

def parse_git_diff(diff) -> FileChanges:
    file_pattern = re.compile(r'^\+\+\+ b/(.*_en_US\.properties)$')
    key_value_pattern = re.compile(r'^[+-](\w+\.[\w.]+)=(.*)$')
    changes = {}

    current_file = None
    for line in diff.splitlines():
        file_match = file_pattern.match(line)
        if file_match:
            current_file = file_match.group(1)
            changes[current_file] = []
        
        if current_file:
            kv_match = key_value_pattern.match(line)
            if kv_match:
                key, value = kv_match.groups()
                isNew = True if line.startswith('+') else False
                changes[current_file].append((key, value, isNew))

    return changes

def main():
    diff = get_last_commit_diff(repo_path=None)
    if diff:
        changes = parse_git_diff(diff)
        for file, modifications in changes.items():
            print(f"Changed file: {file}")
            for key, value, change_type in modifications:
                print(f" - {key} = {value} ({change_type})")
    else:
        print("No changes detected in the last commit.")

if __name__ == "__main__":
    main()