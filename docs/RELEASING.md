# Releasing

Releases are cut from `main` by the **Release** workflow (`.github/workflows/release.yml`).

1. Make sure everything for the release is merged into `main`.
2. Go to **Actions → Release → Run workflow**. Run it on `main`.
3. Pick a bump (`patch`, `minor` or `major`), or type an explicit version such as `0.5.0` or `0.4.7.1`. An explicit version wins over the bump and must be greater than the current one.

The workflow then:

- runs the full test suite and stops if anything fails;
- bumps `version` in `custom_components/dess_monitor/manifest.json` and commits `Bump manifest to X.Y.Z` to `main` as `github-actions[bot]`;
- tags `vX.Y.Z` and pushes the commit and the tag together (atomically). If `main` moved during the run, nothing is pushed;
- publishes the GitHub Release (marked Latest) with notes listing the commits and merged PRs since the previous tag.

HACS picks up the new release automatically. You can edit the release notes on GitHub afterwards if needed.

Bump rules: `patch` 0.4.6 → 0.4.7, `minor` → 0.5.0, `major` → 1.0.0. A fourth version part (`0.4.3.4`) is dropped by any bump.

Don't edit the manifest version by hand. If a tag is ever pushed manually, the **Version Guard** workflow still checks that it matches the manifest.
