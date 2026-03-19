class RuntimeAssetMode {
  static bool useOnlineMaps = true;
  static bool useOnlineFonts = true;
}

class OnlineAssetAvailability {
  final bool maps;
  final bool fonts;

  const OnlineAssetAvailability({
    required this.maps,
    required this.fonts,
  });
}
