Stilwater - a Saints Row 2 client by holdonquietly.com

Install
  You need Saints Row 2 from Steam, installed. That's all.
  Extract this whole zip anywhere, then double-click install.bat. It sets up everything else:
    - Juiced Patch v9.2.0 (downloaded from its GitHub release), which Stilwater builds on
    - the game exe made mod-ready, and allowed to use 4 GB of memory
    - DirectX 9 for the game, and the .NET 8 Desktop Runtime from Microsoft, if they're missing
    - the Stilwater core, launcher and mods
    - DXVK, if your graphics card supports Vulkan
    - Steam's Play button opening Stilwater (it asks before closing Steam for a moment)
    - a Stilwater shortcut on your desktop
  Windows may ask for permission once (when the game is in Program Files, or DirectX is needed).
  Game somewhere else? install.bat -Game "D:\Games\Saints Row 2"

Update
  The launcher shows an Update button when a new version is out. Close the game first.

Online co-op
  Friends tab: create an account (or sign in), add friends by nick and invite them.
  The game signs in with the same account.

Uninstall
  Delete <Saints Row 2>\Stilwater and the "STILWATER - ..." folders in <Saints Row 2>\mods, and copy
  the files in <Saints Row 2>\_backup_pre_stilwater back into <Saints Row 2>. Or in Steam: Saints
  Row 2 > Properties > Installed Files > Verify integrity, which restores the game's own files.

Credits
  Juiced Patch by the Juiced Team (GPL-3.0): https://github.com/kobraworksmodding/Saints-Row-2-Juiced-Patch
  DXVK by Philip Rebohle and contributors (zlib): https://github.com/doitsujin/dxvk
