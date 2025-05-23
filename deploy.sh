#!/bin/bash
set -e

git checkout -B deployments &&
git push origin deployments --force &&
git checkout -
