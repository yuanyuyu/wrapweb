# Copyright 2015 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import sys, os, re
import urllib.request, json, hashlib
import tempfile
import git
import shutil

from mesonwrap import upstream
from mesonwrap.tools import environment


def print_status(msg, check):
    '''
    Prints msg with success indicator based on check parameter.
    Returns: check
    '''
    OK_CHR = '\u2611'
    FAIL_CHR = '\u2612'
    status = OK_CHR if check else FAIL_CHR
    print('{msg}: {status}'.format(msg=msg, status=status))
    return check


class Reviewer:
    def __init__(self, project, pull_id):
        self._github = environment.Github()
        self._org = self._github.get_organization('mesonbuild')
        self._project = self._org.get_repo(project)
        self._pull = self._project.get_pull(pull_id)

    def review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            return self.review_int(tmpdir)

    def review_int(self, tmpdir):
        head_dir = os.path.join(tmpdir, 'head')
        project = self._pull.base.repo.name
        branch = self._pull.base.ref
        head_repo = git.Repo.clone_from(self._pull.head.repo.clone_url, head_dir,
                                        branch=self._pull.head.ref)
        if not self.check_basics(head_repo, project, branch): return False
        if not self.check_files(head_dir): return False
        upwrap = upstream.UpstreamWrap.from_file(os.path.join(head_dir, 'upstream.wrap'))
        if not self.check_wrapformat(upwrap): return False
        if not self.check_download(tmpdir, upwrap): return False
        if not self.check_extract(tmpdir, upwrap): return False
        return True

    @staticmethod
    def check_has_no_path_separators(name, value):
        return print_status(name + ' has no path separators',
                            '/' not in value and '\\' not in value)

    def check_wrapformat(self, upwrap):
        if not print_status('upstream.wrap has directory', upwrap.has_directory): return False
        if not self.check_has_no_path_separators('upstream.wrap directory',
                                                 upwrap.directory): return False
        if not print_status('upstream.wrap has source_url', upwrap.has_source_url): return False
        if not print_status('upstream.wrap has source_filename', upwrap.has_source_filename): return False
        if not self.check_has_no_path_separators('upstream.wrap source_filename',
                                                 upwrap.source_filename): return False
        if not print_status('upstream.wrap has source_hash', upwrap.has_source_hash): return False
        return True

    def check_files(self, head_dir):
        found = False
        permitted_files = ['upstream.wrap', 'meson.build', 'readme.txt',
                           'meson_options.txt', '.gitignore', 'LICENSE.build']
        for root, dirs, files in os.walk(head_dir):
            if '.git' in dirs:
                dirs.remove('.git')
            for fname in files:
                if fname not in permitted_files:
                    if not found:
                        print('Non-buildsystem files found:')
                    found = True
                    abs_name = os.path.join(root, fname)
                    rel_name = abs_name[len(head_dir)+1:]
                    print(' ', rel_name)
        if not print_status('Repo contains only buildsystem files', not found):
            return False
        return True

    @staticmethod
    def isfile(head_dir, filename):
        return os.path.isfile(os.path.join(head_dir, filename))

    def check_basics(self, head_repo, project, branch):
        print('Inspecting project %s, branch %s.' % (project, branch))
        head_dir = head_repo.working_dir
        if not print_status('Repo name valid', re.fullmatch('[a-z0-9._]+', project)): return False
        if not print_status('Branch name valid', re.fullmatch('[a-z0-9._]+', branch)): return False
        if not print_status('Target branch is not master', branch != 'master'): return False
        if not print_status('Has readme.txt', self.isfile(head_dir, 'readme.txt')): return False
        if not print_status('Has LICENSE.build', self.isfile(head_dir, 'LICENSE.build')): return False
        if not print_status('Has upstream.wrap', self.isfile(head_dir, 'upstream.wrap')): return False
        if not print_status('Has toplevel meson.build', self.isfile(head_dir, 'meson.build')): return False
        return True

    @staticmethod
    def _fetch(url):
        data = None
        exc = None
        try:
            with urllib.request.urlopen(url) as u:
                data = u.read()
        except Exception as e:
            exc = e
        return (data, exc)

    def check_download(self, tmpdir, upwrap):
        source_data, download_exc = self._fetch(upwrap.source_url)
        if not print_status('Download url works', download_exc is None):
            print(' error:', str(e))
            return False
        with open(os.path.join(tmpdir, upwrap.source_filename), 'wb') as f:
            f.write(source_data)
        h = hashlib.sha256()
        h.update(source_data)
        calculated_hash = h.hexdigest()
        if not print_status('Hash matches', calculated_hash == upwrap.source_hash):
            print(' expected:', upwrap.source_hash)
            print('      got:', calculated_hash)
            return False
        return True

    def check_extract(self, tmpdir, upwrap):
        # TODO lead_directory_missing
        srcdir = os.path.join(tmpdir, 'src')
        os.mkdir(srcdir)
        shutil.unpack_archive(os.path.join(tmpdir, upwrap.source_filename), srcdir)
        srcdir = os.path.join(srcdir, upwrap.directory)
        if not print_status('upstream.wrap directory {!r} exists'.format(upwrap.directory),
                            os.path.exists(srcdir)): return False
        shutil.copytree(os.path.join(tmpdir, 'head'), srcdir,
                        ignore=shutil.ignore_patterns('.git', 'readme.txt', 'upstream.wrap'))
        return True


def main(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('name')
    parser.add_argument('pull_request', type=int)
    args = parser.parse_args(args)
    r = Reviewer(args.name, args.pull_request)
    if not r.review():
        sys.exit(1)