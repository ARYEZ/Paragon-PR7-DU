# Changelog

## 0.1.0

- First release: shows what fills a disk, the way WizTree does. With administrator rights it reads an NTFS drive's
  own index (the Master File Table) in one go; otherwise it walks the folders. It has a tree of folders with "% of
  parent" bars, the biggest files on the drive, file types, and a treemap where each file is a block coloured by its
  kind and linked to the lists. Right-click to open a file, show it in its folder (PR7-E when it's your folder app),
  copy its path or delete it to the Recycle Bin (totals update without a rescan). OBSIDIAN and AURORA finishes; it
  updates itself like the other family apps.
