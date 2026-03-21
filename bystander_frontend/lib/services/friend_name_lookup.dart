import 'dart:convert';

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:crypto/crypto.dart';

/// SHA-256 doc id for `user_lookup` (same hashing as friends / profile flows).
String friendEmailHash(String email) {
  final normalized = email.trim().toLowerCase();
  final digest = sha256.convert(utf8.encode(normalized));
  return digest.toString();
}

/// Profile names from `user_lookup` when a friend document omits first/last.
Future<Map<String, String>> lookupNameFromUserLookup(String email) async {
  final trimmed = email.trim().toLowerCase();
  if (trimmed.isEmpty) {
    return {'firstName': '', 'lastName': ''};
  }
  final snap = await FirebaseFirestore.instance
      .collection('user_lookup')
      .doc(friendEmailHash(trimmed))
      .get();
  final data = snap.data();
  if (data == null) {
    return {'firstName': '', 'lastName': ''};
  }
  return {
    'firstName': (data['firstName'] as String?)?.trim() ?? '',
    'lastName': (data['lastName'] as String?)?.trim() ?? '',
  };
}

/// "ชื่อ นามสกุล" for lists; falls back to email or a generic label.
String formatFriendListLabel(String first, String last, String email) {
  final f = first.trim();
  final l = last.trim();
  var label = [f, l].where((s) => s.isNotEmpty).join(' ');
  if (label.isEmpty) {
    final e = email.trim();
    label = e.isNotEmpty ? e : 'เพื่อน';
  }
  return label;
}
