# Requirements delta

### WIN-01 Same guarantees on Windows
`EvidenceStore` works on native Windows with the DE-05 guarantees: evidence
never leaves the case directory, links, junctions and hardlinks are refused,
a replaced case directory is detected, case directories are exclusive, and the
base must be private to the current user.

- Given a case directory replaced by a junction or another directory, every
  read, append and snapshot write fails and writes nothing outside it.
- Given an artifact replaced by a symlink or a hardlink, the operation fails and
  the external file is unchanged.
- Given a base whose DACL grants access to anyone other than the user, SYSTEM or
  Administrators, the store refuses with `PermissionError`.

### WIN-02 CLI and doctor
`autodebug serve --demo` runs on Windows; `doctor` reports evidence storage as
supported and checks folder privacy through the DACL.

### WIN-03 Verification
The full test suite runs on Windows CI (Python 3.11 and 3.12), including
Windows-specific escape tests.
