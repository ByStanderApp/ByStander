import 'dart:convert';

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:crypto/crypto.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

class FriendsScreen extends StatefulWidget {
  const FriendsScreen({super.key});

  @override
  State<FriendsScreen> createState() => _FriendsScreenState();
}

class _FriendsScreenState extends State<FriendsScreen> {
  final _emailController = TextEditingController();
  bool _isLoading = true;
  bool _isSending = false;
  bool _isAccepting = false;
  bool _isRemovingFriend = false;

  final List<_IncomingFriendRequest> _incoming = [];
  final List<_FriendRow> _friends = [];

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void dispose() {
    _emailController.dispose();
    super.dispose();
  }

  String _emailHash(String email) {
    final normalized = email.trim().toLowerCase();
    final digest = sha256.convert(utf8.encode(normalized));
    return digest.toString();
  }

  /// Combines profile first + last name for display (Thai UI).
  String _formatFullName(String first, String last) {
    final f = first.trim();
    final l = last.trim();
    if (f.isEmpty && l.isEmpty) return '';
    if (f.isEmpty) return l;
    if (l.isEmpty) return f;
    return '$f $l';
  }

  Future<Map<String, String>> _getMyNameSnapshot() async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return {'firstName': '', 'lastName': ''};

    final snap = await FirebaseFirestore.instance
        .collection('users')
        .doc(user.uid)
        .get();
    final data = snap.data() ?? {};

    final first = (data['firstName'] as String?)?.trim() ?? '';
    final last = (data['lastName'] as String?)?.trim() ?? '';

    if (first.isNotEmpty || last.isNotEmpty) {
      return {'firstName': first, 'lastName': last};
    }

    // Fallback if user never saved profile fields.
    final display = (user.displayName ?? '').trim();
    final parts =
        display.split(RegExp(r'\s+')).where((p) => p.isNotEmpty).toList();
    final firstFallback = parts.isNotEmpty ? parts.first : display;
    final lastFallback = parts.length > 1 ? parts.sublist(1).join(' ') : '';
    return {'firstName': firstFallback, 'lastName': lastFallback};
  }

  /// Names saved on profile update (`user_lookup`). Used to fill missing
  /// `otherLastName` / `requesterLastName` on older friend payloads.
  Future<Map<String, String>> _lookupNameFromUserLookup(String email) async {
    final trimmed = email.trim().toLowerCase();
    if (trimmed.isEmpty) {
      return {'firstName': '', 'lastName': ''};
    }
    final snap = await FirebaseFirestore.instance
        .collection('user_lookup')
        .doc(_emailHash(trimmed))
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

  Future<_FriendRow> _enrichFriendRow(_FriendRow f) async {
    if (f.otherEmail.isEmpty) return f;
    final lookup = await _lookupNameFromUserLookup(f.otherEmail);
    return _FriendRow(
      otherUid: f.otherUid,
      firstName: f.firstName.isNotEmpty ? f.firstName : lookup['firstName']!,
      lastName: f.lastName.isNotEmpty ? f.lastName : lookup['lastName']!,
      otherEmail: f.otherEmail,
      relationship: f.relationship,
    );
  }

  Future<_IncomingFriendRequest> _enrichIncoming(
      _IncomingFriendRequest r) async {
    if (r.requesterEmail.isEmpty) return r;
    final lookup = await _lookupNameFromUserLookup(r.requesterEmail);
    return _IncomingFriendRequest(
      requesterUid: r.requesterUid,
      requesterFirstName: r.requesterFirstName.isNotEmpty
          ? r.requesterFirstName
          : lookup['firstName']!,
      requesterLastName: r.requesterLastName.isNotEmpty
          ? r.requesterLastName
          : lookup['lastName']!,
      requesterEmail: r.requesterEmail,
    );
  }

  Future<void> _reload() async {
    setState(() => _isLoading = true);
    try {
      final user = FirebaseAuth.instance.currentUser;
      if (user == null) {
        _incoming.clear();
        _friends.clear();
        return;
      }

      final uid = user.uid;
      final firestore = FirebaseFirestore.instance;

      final friendSnap = await firestore
          .collection('users')
          .doc(uid)
          .collection('friends')
          .get();
      final friends = friendSnap.docs.map((d) {
        final data = d.data();
        return _FriendRow(
          otherUid: d.id,
          firstName: (data['otherFirstName'] as String?)?.trim() ?? '',
          lastName: (data['otherLastName'] as String?)?.trim() ?? '',
          otherEmail: (data['otherEmail'] as String?)?.trim() ?? '',
          relationship: (data['relationship'] as String?)?.trim() ?? '',
        );
      }).toList();

      final incomingSnap = await firestore
          .collection('users')
          .doc(uid)
          .collection('incoming_friend_requests')
          .get();
      final incoming = incomingSnap.docs.map((d) {
        final data = d.data();
        return _IncomingFriendRequest(
          requesterUid: d.id,
          requesterFirstName:
              (data['requesterFirstName'] as String?)?.trim() ?? '',
          requesterLastName:
              (data['requesterLastName'] as String?)?.trim() ?? '',
          requesterEmail: (data['requesterEmail'] as String?)?.trim() ?? '',
        );
      }).toList();

      final enrichedFriends = await Future.wait(friends.map(_enrichFriendRow));
      final enrichedIncoming = await Future.wait(incoming.map(_enrichIncoming));

      setState(() {
        _friends
          ..clear()
          ..addAll(enrichedFriends);
        _incoming
          ..clear()
          ..addAll(enrichedIncoming);
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('โหลดเพื่อนไม่สำเร็จ: ${e.toString()}')),
        );
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _sendFriendRequest() async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;
    if (_isSending) return;

    final email = _emailController.text.trim();
    if (email.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('กรุณากรอกอีเมลเพื่อน')),
      );
      return;
    }

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('ความเป็นส่วนตัวและการเข้าถึงข้อมูล'),
        content: const SingleChildScrollView(
          child: Text(
            'เมื่อเป็นเพื่อนกันแล้ว ทั้งสองฝ่ายสามารถใช้ข้อมูลโปรไฟล์ของอีกฝ่าย '
            'ในการขอคำแนะนำฉุกเฉินได้ รวมถึงข้อมูลส่วนตัว ประวัติทางการแพทย์ '
            'และผู้ติดต่อฉุกเฉินตามที่บันทึกไว้ในแอป\n\n'
            'เพื่อความปลอดภัย ควรเพิ่มเฉพาะคนที่ไว้ใจได้มากที่สุด '
            '(เช่น ครอบครัวหรือคนใกล้ชิด) เท่านั้น\n\n'
            'ต้องการส่งคำขอเป็นเพื่อนต่อหรือไม่?',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('ยกเลิก'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('ยอมรับและส่งคำขอ'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _isSending = true);
    try {
      final uid = user.uid;
      final firestore = FirebaseFirestore.instance;
      final emailHash = _emailHash(email);

      final lookupSnap =
          await firestore.collection('user_lookup').doc(emailHash).get();
      final lookupData = lookupSnap.data();
      final otherUid = (lookupData?['uid'] as String?)?.trim() ?? '';
      if (otherUid.isEmpty) {
        throw Exception('ไม่พบผู้ใช้จากอีเมลนี้');
      }
      if (otherUid == uid) {
        throw Exception('ไม่สามารถส่งคำขอต่อตัวเองได้');
      }

      final existingFriendSnap = await firestore
          .collection('users')
          .doc(uid)
          .collection('friends')
          .doc(otherUid)
          .get();
      if (existingFriendSnap.exists) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('คุณเป็นเพื่อนกันแล้ว')),
          );
        }
        return;
      }

      final myName = await _getMyNameSnapshot();

      await firestore
          .collection('users')
          .doc(otherUid)
          .collection('incoming_friend_requests')
          .doc(uid)
          .set({
        'requesterFirstName': myName['firstName'] ?? '',
        'requesterLastName': myName['lastName'] ?? '',
        'requesterEmail': (user.email ?? '').trim(),
        'createdAt': FieldValue.serverTimestamp(),
      }, SetOptions(merge: true));

      _emailController.clear();
      await _reload();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('ส่งคำขอเพื่อนแล้ว รออีกฝ่ายยืนยัน')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('ส่งคำขอไม่สำเร็จ: ${e.toString()}')),
        );
      }
    } finally {
      if (mounted) setState(() => _isSending = false);
    }
  }

  Future<void> _acceptRequest(_IncomingFriendRequest req) async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;
    if (_isAccepting) return;

    setState(() => _isAccepting = true);
    try {
      final uid = user.uid;
      final firestore = FirebaseFirestore.instance;

      final myName = await _getMyNameSnapshot();
      final myFirst = myName['firstName'] ?? '';
      final myLast = myName['lastName'] ?? '';
      final theirFirst = req.requesterFirstName;
      final theirLast = req.requesterLastName;
      final myEmail = (user.email ?? '').trim();
      final theirEmail = req.requesterEmail;

      // Friend doc for me.
      await firestore
          .collection('users')
          .doc(uid)
          .collection('friends')
          .doc(req.requesterUid)
          .set({
        'otherFirstName': theirFirst,
        if (theirLast.isNotEmpty) 'otherLastName': theirLast,
        if (theirEmail.isNotEmpty) 'otherEmail': theirEmail,
        'relationship': '',
        'acceptedAt': FieldValue.serverTimestamp(),
      }, SetOptions(merge: true));

      // Reciprocal friend doc for the requester.
      await firestore
          .collection('users')
          .doc(req.requesterUid)
          .collection('friends')
          .doc(uid)
          .set({
        'otherFirstName': myFirst,
        if (myLast.isNotEmpty) 'otherLastName': myLast,
        if (myEmail.isNotEmpty) 'otherEmail': myEmail,
        'relationship': '',
        'acceptedAt': FieldValue.serverTimestamp(),
      }, SetOptions(merge: true));

      // Remove the incoming request.
      await firestore
          .collection('users')
          .doc(uid)
          .collection('incoming_friend_requests')
          .doc(req.requesterUid)
          .delete();

      await _reload();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('ยืนยันคำขอเพื่อนแล้ว')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('ยืนยันไม่สำเร็จ: ${e.toString()}')),
        );
      }
    } finally {
      if (mounted) setState(() => _isAccepting = false);
    }
  }

  Future<void> _confirmRemoveFriend(_FriendRow friend) async {
    final display = _formatFullName(friend.firstName, friend.lastName);
    final name = display.isNotEmpty ? display : 'เพื่อน';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('ลบเพื่อน'),
        content: Text('ต้องการลบ "$name" ออกจากรายชื่อเพื่อนหรือไม่?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('ยกเลิก'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('ลบ'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await _removeFriend(friend);
  }

  Future<void> _removeFriend(_FriendRow friend) async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;
    if (_isRemovingFriend) return;

    setState(() => _isRemovingFriend = true);
    try {
      final myUid = user.uid;
      final otherUid = friend.otherUid;
      final firestore = FirebaseFirestore.instance;

      final batch = firestore.batch();
      batch.delete(
        firestore
            .collection('users')
            .doc(myUid)
            .collection('friends')
            .doc(otherUid),
      );
      batch.delete(
        firestore
            .collection('users')
            .doc(otherUid)
            .collection('friends')
            .doc(myUid),
      );
      await batch.commit();

      await _reload();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('ลบเพื่อนแล้ว')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('ลบเพื่อนไม่สำเร็จ: ${e.toString()}')),
        );
      }
    } finally {
      if (mounted) setState(() => _isRemovingFriend = false);
    }
  }

  Future<void> _rejectRequest(_IncomingFriendRequest req) async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;

    try {
      await FirebaseFirestore.instance
          .collection('users')
          .doc(user.uid)
          .collection('incoming_friend_requests')
          .doc(req.requesterUid)
          .delete();
      await _reload();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('ปฏิเสธไม่สำเร็จ: ${e.toString()}')),
        );
      }
    }
  }

  Future<void> _editRelationship(_FriendRow friend) async {
    var draftValue = friend.relationship;
    final updated = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('ความสัมพันธ์กับเพื่อน'),
        content: TextFormField(
          initialValue: friend.relationship,
          autofocus: true,
          onChanged: (value) => draftValue = value,
          decoration: const InputDecoration(
            labelText: 'เช่น พ่อ แม่ ญาติผู้ใหญ่ เพื่อน',
            border: OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('ยกเลิก'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(draftValue.trim()),
            child: const Text('บันทึก'),
          ),
        ],
      ),
    );
    if (updated == null) return;
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;

    try {
      await FirebaseFirestore.instance
          .collection('users')
          .doc(user.uid)
          .collection('friends')
          .doc(friend.otherUid)
          .set({'relationship': updated}, SetOptions(merge: true));
      await _reload();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('บันทึกความสัมพันธ์แล้ว')),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('บันทึกไม่สำเร็จ: ${e.toString()}')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('รายชื่อเพื่อน'),
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : SafeArea(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            const Text(
                              'เพิ่มเพื่อนด้วยอีเมล',
                              style: TextStyle(fontWeight: FontWeight.bold),
                            ),
                            const SizedBox(height: 12),
                            TextField(
                              controller: _emailController,
                              decoration: const InputDecoration(
                                labelText: 'อีเมลของเพื่อน',
                                border: OutlineInputBorder(),
                              ),
                              keyboardType: TextInputType.emailAddress,
                            ),
                            const SizedBox(height: 12),
                            FilledButton(
                              onPressed: _isSending ? null : _sendFriendRequest,
                              child: _isSending
                                  ? const SizedBox(
                                      width: 18,
                                      height: 18,
                                      child: CircularProgressIndicator(
                                          strokeWidth: 2),
                                    )
                                  : const Text('ส่งคำขอเพื่อน'),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        'เพื่อนที่ยืนยันแล้ว',
                        style: TextStyle(fontWeight: FontWeight.bold),
                      ),
                    ),
                    const SizedBox(height: 8),
                    if (_friends.isEmpty)
                      const Text('ยังไม่มีเพื่อนที่ยืนยันแล้ว')
                    else
                      ListView.builder(
                        shrinkWrap: true,
                        physics: const NeverScrollableScrollPhysics(),
                        itemCount: _friends.length,
                        itemBuilder: (context, i) {
                          final f = _friends[i];
                          final fullName =
                              _formatFullName(f.firstName, f.lastName);
                          final titleText =
                              fullName.isNotEmpty ? fullName : 'เพื่อน';
                          return Card(
                            child: ListTile(
                              title: Text(titleText),
                              subtitle: Text(
                                [
                                  if (f.relationship.isNotEmpty)
                                    'ความสัมพันธ์: ${f.relationship}',
                                  if (f.otherEmail.isNotEmpty) f.otherEmail,
                                ].join('\n'),
                              ),
                              trailing: SizedBox(
                                width: 96,
                                child: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    IconButton(
                                      tooltip: 'แก้ไขความสัมพันธ์',
                                      icon: const Icon(Icons.edit_outlined),
                                      onPressed: () => _editRelationship(f),
                                    ),
                                    IconButton(
                                      tooltip: 'ลบเพื่อน',
                                      icon: Icon(
                                        Icons.person_remove_outlined,
                                        color: theme.colorScheme.error,
                                      ),
                                      onPressed: _isRemovingFriend
                                          ? null
                                          : () => _confirmRemoveFriend(f),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          );
                        },
                      ),
                    const SizedBox(height: 16),
                    const Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        'คำขอที่คุณได้รับ',
                        style: TextStyle(fontWeight: FontWeight.bold),
                      ),
                    ),
                    const SizedBox(height: 8),
                    if (_incoming.isEmpty)
                      const Text('ไม่มีคำขอเพื่อน')
                    else
                      ListView.builder(
                        shrinkWrap: true,
                        physics: const NeverScrollableScrollPhysics(),
                        itemCount: _incoming.length,
                        itemBuilder: (context, i) {
                          final req = _incoming[i];
                          final incomingName = _formatFullName(
                            req.requesterFirstName,
                            req.requesterLastName,
                          );
                          final titleText =
                              incomingName.isNotEmpty ? incomingName : 'ผู้ขอ';
                          return Card(
                            child: ListTile(
                              title: Text(titleText),
                              subtitle: req.requesterEmail.isNotEmpty
                                  ? Text(req.requesterEmail)
                                  : null,
                              trailing: SizedBox(
                                width: 96,
                                child: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    IconButton(
                                      tooltip: 'ยืนยัน',
                                      icon: const Icon(
                                        Icons.check_circle_outline,
                                        color: Colors.green,
                                      ),
                                      onPressed: _isAccepting
                                          ? null
                                          : () => _acceptRequest(req),
                                    ),
                                    IconButton(
                                      tooltip: 'ปฏิเสธ',
                                      icon: Icon(
                                        Icons.cancel_outlined,
                                        color: theme.colorScheme.error,
                                      ),
                                      onPressed: () => _rejectRequest(req),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          );
                        },
                      ),
                  ],
                ),
              ),
            ),
    );
  }
}

class _FriendRow {
  final String otherUid;
  final String firstName;
  final String lastName;
  final String otherEmail;
  final String relationship;
  _FriendRow({
    required this.otherUid,
    required this.firstName,
    this.lastName = '',
    this.otherEmail = '',
    this.relationship = '',
  });
}

class _IncomingFriendRequest {
  final String requesterUid;
  final String requesterFirstName;
  final String requesterLastName;
  final String requesterEmail;
  _IncomingFriendRequest({
    required this.requesterUid,
    required this.requesterFirstName,
    this.requesterLastName = '',
    this.requesterEmail = '',
  });
}
