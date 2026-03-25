import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';

String inferPronounFromRelationship(String relationship, {String gender = ''}) {
  final rel = relationship.trim().toLowerCase();
  final normalizedGender = gender.trim().toLowerCase();
  if ({'แม่', 'มารดา', 'wife', 'mother', 'mom', 'female'}.contains(rel)) {
    return 'she';
  }
  if ({'พ่อ', 'บิดา', 'husband', 'father', 'dad', 'male'}.contains(rel)) {
    return 'he';
  }
  if (normalizedGender == 'female' || normalizedGender == 'หญิง') {
    return 'she';
  }
  if (normalizedGender == 'male' || normalizedGender == 'ชาย') {
    return 'he';
  }
  return 'they';
}

class CachedMedicalPerson {
  final String uid;
  final String name;
  final String relationship;
  final String gender;
  final List<String> conditions;
  final List<String> allergies;
  final List<String> immunizations;

  const CachedMedicalPerson({
    required this.uid,
    required this.name,
    this.relationship = '',
    this.gender = '',
    this.conditions = const [],
    this.allergies = const [],
    this.immunizations = const [],
  });
}

bool hasMedicalHistoryEntries(List<CachedMedicalPerson> individuals) {
  return individuals.any(
    (person) =>
        person.conditions.isNotEmpty ||
        person.allergies.isNotEmpty ||
        person.immunizations.isNotEmpty,
  );
}

Map<String, dynamic> buildMedicalContextPayload({
  required List<CachedMedicalPerson> individuals,
  String? callerUserId,
  String? targetUserId,
}) {
  return {
    'individuals': individuals
        .where((person) => person.uid.trim().isNotEmpty)
        .map((person) => {
              'uid': person.uid,
              'name': person.name,
              'relationship': person.relationship,
              'pronoun': inferPronounFromRelationship(
                person.relationship,
                gender: person.gender,
              ),
              'conditions': person.conditions,
              'allergies': person.allergies,
              'immunizations': person.immunizations,
              'is_caller': callerUserId != null && person.uid == callerUserId,
              'is_target': targetUserId != null && person.uid == targetUserId,
            })
        .toList(),
  };
}

class MedicalContextCacheService {
  MedicalContextCacheService._();

  static final MedicalContextCacheService instance =
      MedicalContextCacheService._();

  final FirebaseFirestore _firestore = FirebaseFirestore.instance;
  final FirebaseAuth _auth = FirebaseAuth.instance;

  List<CachedMedicalPerson> _cachedIndividuals = const [];

  List<CachedMedicalPerson> get cachedIndividuals => _cachedIndividuals;

  bool get hasMedicalHistory => hasMedicalHistoryEntries(_cachedIndividuals);

  Future<void> refresh() async {
    final user = _auth.currentUser;
    if (user == null) {
      _cachedIndividuals = const [];
      return;
    }

    try {
      final selfFuture = _loadUserSnapshot(
        userId: user.uid,
        fallbackName: (user.displayName ?? '').trim(),
      );
      final friendsFuture = _firestore
          .collection('users')
          .doc(user.uid)
          .collection('friends')
          .get();
      final results = await Future.wait([selfFuture, friendsFuture]);
      final self = results[0] as CachedMedicalPerson;
      final friendDocs =
          (results[1] as QuerySnapshot<Map<String, dynamic>>).docs;

      final friendFutures = friendDocs.map((doc) {
        final data = doc.data();
        final fallbackName = [
          (data['otherFirstName'] as String?)?.trim() ?? '',
          (data['otherLastName'] as String?)?.trim() ?? '',
        ].where((value) => value.isNotEmpty).join(' ');
        return _loadUserSnapshot(
          userId: doc.id,
          fallbackName: fallbackName,
          relationship: (data['relationship'] as String?)?.trim() ?? '',
        );
      });

      final friends = await Future.wait(friendFutures);
      _cachedIndividuals = [self, ...friends];
    } catch (exc) {
      debugPrint('MedicalContextCacheService.refresh failed: $exc');
    }
  }

  Map<String, dynamic> buildPayload({
    String? callerUserId,
    String? targetUserId,
  }) {
    if (!hasMedicalHistory) {
      return const {};
    }
    return buildMedicalContextPayload(
      individuals: _cachedIndividuals,
      callerUserId: callerUserId,
      targetUserId: targetUserId,
    );
  }

  Future<CachedMedicalPerson> _loadUserSnapshot({
    required String userId,
    String fallbackName = '',
    String relationship = '',
  }) async {
    String firstName = '';
    String lastName = '';
    String gender = '';
    List<String> conditions = const [];
    List<String> allergies = const [];
    List<String> immunizations = const [];

    try {
      final userDoc = await _firestore.collection('users').doc(userId).get();
      final data = userDoc.data() ?? <String, dynamic>{};
      firstName = (data['firstName'] as String?)?.trim() ?? '';
      lastName = (data['lastName'] as String?)?.trim() ?? '';
      gender = (data['gender'] as String?)?.trim() ?? '';
    } catch (_) {
      // Best effort cache warm-up only.
    }

    try {
      final medDoc = await _firestore
          .collection('users')
          .doc(userId)
          .collection('medical_histories')
          .doc('current')
          .get();
      final med = medDoc.data() ?? <String, dynamic>{};
      conditions = _toStringList(med['medicalCondition']);
      allergies = _toStringList(med['allergies']);
      immunizations = _toStringList(med['immunizations']);
    } catch (_) {
      // Non-fatal on latency path.
    }

    final name = [firstName, lastName]
        .where((value) => value.trim().isNotEmpty)
        .join(' ')
        .trim();
    return CachedMedicalPerson(
      uid: userId,
      name: name.isNotEmpty ? name : fallbackName,
      relationship: relationship,
      gender: gender,
      conditions: conditions,
      allergies: allergies,
      immunizations: immunizations,
    );
  }

  List<String> _toStringList(dynamic raw) {
    if (raw is! List) return const [];
    return raw
        .map((item) => item.toString().trim())
        .where((item) => item.isNotEmpty)
        .toList();
  }
}
