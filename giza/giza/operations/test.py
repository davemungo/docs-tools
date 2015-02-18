# Copyright 2015 MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argh
import os
import logging
import subprocess
import shlex

import libgiza.git
import libgiza.app
import libgiza.task

import giza.content.assets
import giza.config.helper
import giza.config.main
import giza.tools.files

logger = logging.getLogger('GIZA.OPERATIONS.TEST')


def setup_test_repo(path, project):
    if os.path.isdir(path):
        g = libgiza.git.GitRepo(path)
        if g.current_branch() != 'master':
            g.checkout_branch('master')
        g.pull(remote='origin', branch='master')
        logger.info('updated repository at: ' + path)
    else:
        g = libgiza.git.GitRepo(os.path.dirname(path))
        g.clone(project.uri, os.path.basename(path))
        logger.info('cloned new repository into: ' + path)

    return project


def get_test_config(args):
    try:
        conf = giza.config.helper.fetch_config(args)
    except RuntimeError:
        path = os.path.join('data', 'build_config.yaml')
        if not os.path.isfile(path):
            logger.warning('must run test from the docs-tools repo, or a giza project directory.')
            raise SystemExit(-1)
        else:
            args.conf_path = path

            conf = giza.config.main.Configuration()
            conf.ingest(args.conf_path)
            conf.runstate = args
            conf.paths.projectroot = os.getcwd()

    return conf


def change_branch(path, branch):
    g = libgiza.git.GitRepo(path)
    tracking = '/'.join(('origin', branch))
    g.checkout_branch(branch, tracking=tracking)
    logger.info('checked out {0} ({1}) in {2}'.format(branch, tracking, g.path))


def run_test_op(cmd, dir):
    g = libgiza.git.GitRepo(dir)

    r = subprocess.call(args=shlex.split(cmd), cwd=dir)
    if r != 0:
        m = 'failure with {0}, in "{1}", ({2})'.format(cmd, dir, g.current_branch())
        logger.error(m)
        raise RuntimeError(m)
    else:
        logger.info('completed {0}, in "{1}", ({2})'.format(cmd, dir, g.current_branch()))
        return 0


integration_targets = ('complete', 'minimal', 'cleanComplete', 'cleanMinimal')


@argh.arg('--branch', '-b', dest='_override_branch', nargs="*", default=None)
@argh.arg('--project', '-p', dest='_override_projects', nargs="*", default=None)
@argh.arg('--operation', '-o', dest='_test_op', default='complete', choices=integration_targets)
@argh.expects_obj
@argh.named('test')
def integration_main(args):
    conf = get_test_config(args)
    app = libgiza.app.BuildApp.new(pool_type=conf.runstate.runner,
                                   pool_size=conf.runstate.pool_size,
                                   force=conf.runstate.force)

    build_path = os.path.join(conf.paths.projectroot, conf.paths.output)
    giza.tools.files.safe_create_directory(build_path)

    for project in conf.test.projects:
        if args._test_op not in project.operations:
            logger.error('operation {0} not defined for project {1}'.format(args._test_op, project))
            continue

        if (args._override_projects is not None and
                project.project not in args._override_projects):
            continue

        if args._override_branch is not None:
            project.branches = args._override_branch

        path = os.path.join(build_path, project.project)
        task = app.add(libgiza.task.Task(job=setup_test_repo,
                                         args=(path, project)))
        for branch in project.branches:
            task = task.add_finalizer(libgiza.task.Task(job=change_branch,
                                                        args=(path, branch)))

            if args._test_op.startswith('clean'):
                task = task.add_finalizer(libgiza.task.Task(job=run_test_op,
                                                            args=('rm -rf build/', path)))
                args._test_op = args._test_op.lower()[5:]

            for op in project.operations[args._test_op]:
                task = task.add_finalizer(libgiza.task.Task(job=run_test_op,
                                                            args=(op, path)))

    app.run()