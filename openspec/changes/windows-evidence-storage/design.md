# Design

| POSIX mechanism (today) | Windows equivalent |
|---|---|
| `O_NOFOLLOW` on every open | `CreateFileW` with `FILE_FLAG_OPEN_REPARSE_POINT`; a handle whose attributes include `FILE_ATTRIBUTE_REPARSE_POINT` (symlink or junction) is rejected |
| Directory pinned by an open `dir_fd`; identity `(st_dev, st_ino)` | Directory opened as a handle **without `FILE_SHARE_DELETE`**, so it cannot be renamed or replaced while held; identity = volume serial number + file index |
| `openat(dir_fd, name)` keeps the file inside the pinned directory | Open `<directory final path>\name`, then require `GetFinalPathNameByHandleW(file)` to be exactly that directory plus that name; a mismatch closes the file (and deletes it if this call created it) |
| `O_CREAT \| O_EXCL` temp file + `renameat` | `CREATE_NEW` temp file, written, then renamed in place with `NtSetInformationFile(FileRenameInformation)` using a bare name (stays in the file's actual directory) |
| Single link, regular file (`st_nlink == 1`, `S_ISREG`) | `nNumberOfLinks == 1`, not a directory, not a reparse point |
| Base owned by user, mode `0700`; new dirs `0700`, files `0600` | Base owner is the current user (or the token's default owner) and every effective allow-ACE is for the user, SYSTEM or Administrators; new directories get a protected DACL `D:P(A;OICI;FA;;;<user>)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)`, which files inherit |
| `mkdir(case, dir_fd=base)` exclusive | `CreateDirectoryW(<base final path>\case)` while the base handle is held; `ERROR_ALREADY_EXISTS` = "case directory already exists" |

Administrators and SYSTEM can read any file on Windows regardless of ACLs, so
granting them access is honest rather than a weakening.

Files are written as UTF-8 with `\n` line endings, identical to POSIX.
