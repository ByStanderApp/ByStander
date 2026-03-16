import 'dart:async';
import 'package:bystander_frontend/services/runtime_asset_mode.dart';

Future<OnlineAssetAvailability> detectOnlineAssetsAvailability({
  Duration timeout = const Duration(seconds: 4),
}) async {
  return const OnlineAssetAvailability(maps: true, fonts: true);
}
