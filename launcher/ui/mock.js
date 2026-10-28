// Sample data for opening the UI in a plain browser (the launcher answers these through Bridge.cs).
"use strict";
window.mock = {
  online: {
    signedIn: true, nick: "dee", profileId: 20000001, bio: "Running Stilwater since day one", avatar: null,
    friends: [
      { id: 20000002, name: "angel", status: "playing", activity: "Playing co-op", avatar: null },
      { id: 20000003, name: "Shaundi", status: "online", activity: "In the Stilwater launcher", avatar: null },
      { id: 20000004, name: "Pierce", status: "offline", activity: "", avatar: null },
      { id: 20000005, name: "Gat", status: "offline", activity: "", avatar: null },
    ],
    requests: [{ id: 20000006, name: "Carlos", avatar: null }],
  },
  async call(method, args) {
    await new Promise(r => setTimeout(r, 120));
    switch (method) {
      case "app.state": return {
        version: "0.2.1", staff: true, canPlay: true, serviceName: "Stilwater Online",
        checks: [
          { name: "Game", ok: true, detail: "E:\\SteamLibrary\\steamapps\\common\\Saints Row 2" },
          { name: "Executable", ok: true, detail: "Unencrypted, 4 GB aware" },
          { name: "Stilwater core", ok: true, detail: "Installed" },
          { name: "DXVK", ok: true, detail: "Installed" },
          { name: "Runtime", ok: true, detail: "Ready" },
          { name: "Juiced Patch", ok: true, detail: "v9.2.0 mods present" },
        ],
      };
      case "app.update": return { version: "0.2.2" };
      case "app.release": return { version: "v0.2.1", date: "October 27, 2026", notes: "Works without Steam.\n\n- install.bat finds the game next to the zip, in Steam, or asks you to pick the folder.\n- The launcher uses the game it's installed in.\n- Glock sounds fixed: they were landing on the flamethrower." };
      case "online.check": return { ok: true, server: "155.138.222.253" };
      case "online.ping": return Math.random() < .03 ? null : Math.round(11 + Math.random() * 6 + (Math.random() < .08 ? 40 : 0));
      case "online.status": return this.online;
      case "online.savedLogin": return { nick: "dee", email: "dee@example.com", hasPassword: true };
      case "app.log": return "18:26:01 Stilwater runtime loaded\n18:26:02 Hooks installed\n18:26:05 Online: signed in as dee";
      case "app.nextVersion": return "0.2.2";
      case "mods.code": return "7F3A-19C4";
      case "mods.list": return { mods: [
        { name: "STILWATER - Glock Switch", display: "Glock Switch", enabled: true, core: false, files: 5, mb: 6.3 },
        { name: "STILWATER - Micro Draco", display: "Micro Draco", enabled: true, core: false, files: 4, mb: 0.5 },
        { name: "STILWATER - iPhone 17 Pro", display: "iPhone 17 Pro", enabled: true, core: false, files: 4, mb: 0.4 },
        { name: "STILWATER - HOQ Tech Fleece", display: "HOQ Tech Fleece", enabled: true, core: false, files: 6, mb: 0.7 },
        { name: "STILWATER - M3 GTR", display: "M3 GTR", enabled: true, core: false, files: 8, mb: 5.3 },
        { name: "STILWATER - Civic", display: "Civic", enabled: false, core: false, files: 8, mb: 7.2 },
        { name: "JUICED - Shaders", display: "Shaders", enabled: true, core: true, files: 140, mb: 4.1 },
        { name: "JUICED - Chunk Fixes", display: "Chunk Fixes", enabled: true, core: true, files: 15, mb: 57.6 },
      ] };
      case "settings.list": return { sections: [
        { title: "Stilwater", items: [
          { id: "Stilwater.MenuText", label: "Main menu text", help: "Shown in capitals. Empty hides it.", kind: "text", value: "holdonquietly.com" },
          { id: "Stilwater.TreeDistance", label: "Tree distance", help: "Multiple of vanilla.", kind: "number", value: "1.5", min: 1, max: 4, step: .25, decimals: 2 },
        ] },
        { title: "Graphics", items: [
          { id: "Graphics.Borderless", label: "Borderless window", help: "", kind: "toggle", value: "1" },
          { id: "Graphics.ShadowMapRes", label: "Shadow quality", help: "", kind: "choice", value: "4096", choices: [{ value: "960", text: "Vanilla" }, { value: "2048", text: "High" }, { value: "4096", text: "Very high" }] },
        ] },
        { title: "Steam", items: [{ id: "steam.setup", label: "Play button opens Stilwater", help: "Set up: Steam's Play opens this launcher.", kind: "button", value: "Set up" }] },
      ] };
      default: return null;
    }
  },
};
