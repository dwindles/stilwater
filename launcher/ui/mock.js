// Sample data for opening the UI in a plain browser (the launcher answers these through Bridge.cs).
"use strict";
window.mock = {
  online: {
    signedIn: true, nick: "dee", profileId: 20000001, bio: "Running Stilwater since day one", avatar: null,
    style: "accent=280;crew=SSC;title=Third Street Saint;color=f2b632;effect=glow",
    friends: [
      { id: 20000002, name: "angel", status: "playing", activity: "Playing co-op", avatar: null, style: "crew=SSC;color=ff6fb5;effect=rainbow" },
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
      case "app.stats": return { hours: 41.3, sessions: 57, last: "Nov 3, 3:31 PM", crashes: [
        { name: "SR2_pc.exe.20261103144012.log", when: "Nov 3, 2:40 PM", where: "0x0090D44E", what: "Access violation reading location 0x00000034" },
        { name: "SR2_pc.exe.20261027140440.log", when: "Oct 27, 2:04 PM", where: "0x00C1C690", what: "Access violation writing location 0x00000000" } ] };
      case "app.crash": return "Unhandled exception at 0x0090D44E in SR2_pc.exe (+0x50d44e): 0xC0000005: Access violation reading location 0x00000034.";
      case "app.play":
        this.copies = (this.copies || 0) + 1;
        return this.copies === 1 ? { ok: true, message: "Saints Row 2 is running." }
          : { ok: true, another: true, message: `Copy ${this.copies} started. Sign it in to Stilwater Online with another account, then join from Pause → Co-op → Join an online game.` };
      case "app.release": return { version: "v0.2.1", date: "October 27, 2026", notes: "Works without Steam.\n\n- install.bat finds the game next to the zip, in Steam, or asks you to pick the folder.\n- The launcher uses the game it's installed in.\n- Glock sounds fixed: they were landing on the flamethrower." };
      case "online.check": return { ok: true, server: "155.138.222.253" };
      case "online.ping": return Math.random() < .03 ? null : Math.round(11 + Math.random() * 6 + (Math.random() < .08 ? 40 : 0));
      case "online.status": return this.online;
      case "online.join": return null;
      case "profile.setStyle": this.online.style = args.style; return null;
      case "profile.setBio": this.online.bio = args.bio; return null;
      case "online.savedLogin": return { nick: "dee", email: "dee@example.com", hasPassword: true };
      case "app.log": return "18:26:01 Stilwater runtime loaded\n18:26:02 Hooks installed\n18:26:05 Online: signed in as dee";
      case "app.nextVersion": return "0.2.2";
      case "mods.code": return "7F3A-19C4";
      case "mods.share": return new Promise(r => setTimeout(() => r({ code: "SW-7KQ2-M4HD", skipped: ["Lowrider Pack/readme.html"] }), 800));
      case "mods.lookUp": return { code: "SW-7KQ2-M4HD", by: "angel", mods: [
        { name: "Lowrider Pack", files: 24, mb: 31.4 }, { name: "Better Rain", files: 3, mb: 1.2 } ] };
      case "mods.install": return new Promise(r => setTimeout(() => r(2), 800));
      case "mods.addFolder": case "mods.addZip": return "Lowrider Pack";
      case "mods.remove": return null;
      case "mods.list": return { mods: [
        { name: "Lowrider Pack", display: "Lowrider Pack", enabled: true, core: false, yours: true, files: 24, mb: 31.4 },
        { name: "Better Rain", display: "Better Rain", enabled: false, core: false, yours: true, files: 3, mb: 1.2 },
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
