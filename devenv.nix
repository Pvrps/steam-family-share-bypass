{pkgs, ...}: {
  profile.python = {
    enable = true;
    pythonPackage = pkgs.python313.withPackages (p: [p.tkinter]);
    nativeLibs = with pkgs; [
      xorg.libX11
      xorg.libXft
    ];
  };
}
