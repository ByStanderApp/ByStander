import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:google_sign_in/google_sign_in.dart';

class PersonalInfoScreen extends StatefulWidget {
  const PersonalInfoScreen({super.key});

  @override
  State<PersonalInfoScreen> createState() => _PersonalInfoScreenState();
}

class _PersonalInfoScreenState extends State<PersonalInfoScreen> {
  final _formKey = GlobalKey<FormState>();
  bool _isLoading = true;
  bool _isSaving = false;
  bool _profileExists = false;
  bool _consentAccepted = false;

  final _firstNameController = TextEditingController();
  final _lastNameController = TextEditingController();
  final _genderController = TextEditingController();
  final _bloodTypeController = TextEditingController();
  DateTime? _selectedDateOfBirth;
  final _phoneController = TextEditingController();
  final List<TextEditingController> _conditionControllers = [];
  final List<TextEditingController> _allergyControllers = [];
  final List<TextEditingController> _immunizationControllers = [];

  /// Emergency contacts (relatives). Each: id, firstName, lastName, tel, relationship, relationshipOther (when OTHER).
  List<Map<String, String>> _relatives = [];
  final List<TextEditingController> _relFirstControllers = [];
  final List<TextEditingController> _relLastControllers = [];
  final List<TextEditingController> _relTelControllers = [];
  final List<TextEditingController> _relOtherControllers = [];

  bool _isGoogleLoading = false;
  String? _googleError;

  static const String _consentDialogTitle = 'ข้อตกลงและความยินยอมในการเก็บรวบรวม ใช้ และเปิดเผยข้อมูล';

  static const String _consentDialogBody =
      'แอปพลิเคชัน ByStander ขอความยินยอมจากท่านในการเก็บรวบรวม ใช้ และเก็บรักษาข้อมูลส่วนตัวและข้อมูลสุขภาพของท่าน ดังนี้\n\n'
      '1. ข้อมูลที่เก็บรวบรวม\n'
      '• ข้อมูลส่วนตัว: ชื่อ-นามสกุล เพศ วันเกิด อายุ เบอร์โทรศัพท์ และอีเมล (จากบัญชีที่ใช้เข้าสู่ระบบ)\n'
      '• ข้อมูลสุขภาพ: หมู่เลือด โรคประจำตัว ยาที่แพ้ ยาที่ดื้อ/ immunization และข้อมูลอื่นที่ท่านกรอก\n'
      '• ข้อมูลผู้ติดต่อฉุกเฉิน: ชื่อ เบอร์โทร และความสัมพันธ์\n\n'
      '2. วัตถุประสงค์ของการใช้ข้อมูล\n'
      '• ใช้เพื่อให้คำแนะนำหรือข้อมูลเบื้องต้นในสถานการณ์ฉุกเฉิน (เช่น การปฐมพยาบาล) ที่เกี่ยวข้องกับท่าน\n'
      '• ใช้เพื่อแสดงหรือส่งต่อข้อมูลที่เกี่ยวข้องให้ผู้ติดต่อฉุกเฉินเมื่อมีความจำเป็น\n'
      '• ใช้เพื่อปรับปรุงการให้บริการภายในแอป\n\n'
      '3. การเก็บรักษาและความปลอดภัย\n'
      '• ข้อมูลจะถูกจัดเก็บบนระบบคลาวด์ (Firebase) ที่มีมาตรฐานความปลอดภัย\n'
      '• ข้อมูลของท่านจะถูกใช้เฉพาะตามวัตถุประสงค์ข้างต้น และไม่ขายหรือเปิดเผยให้บุคคลภายนอกโดยไม่มีเหตุอันสมควร\n\n'
      '4. สิทธิของท่าน\n'
      '• ท่านสามารถเข้าถึง แก้ไข หรือลบข้อมูลส่วนตัวและข้อมูลสุขภาพของท่านได้ตลอดเวลาผ่านหน้าจอข้อมูลส่วนตัว\n'
      '• ท่านสามารถถอนความยินยอมได้โดยการลบข้อมูลหรือออกจากระบบ\n'
      '• การไม่ให้ความยินยอมหรือถอนความยินยอมอาจทำให้ไม่สามารถใช้ฟีเจอร์บางอย่างของแอปได้\n\n'
      'โดยการกดยอมรับ ท่านยืนยันว่าท่านได้อ่าน เข้าใจ และยินยอมตามข้อตกลงและนโยบายข้างต้น';

  Future<void> _showConsentDialog() async {
    await showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text(_consentDialogTitle),
        content: const SingleChildScrollView(
          child: Text(_consentDialogBody),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('ปิด'),
          ),
        ],
      ),
    );
  }

  Future<void> _confirmSignOut() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('ออกจากระบบ?'),
        content: const Text('คุณต้องการออกจากระบบใช่หรือไม่'),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('ยกเลิก')),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('ออกจากระบบ'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await _signOut();
    }
  }

  Future<void> _signOut() async {
    try {
      // Sign out from both Firebase and Google provider (web/mobile)
      await GoogleSignIn().signOut();
    } catch (e) {
      debugPrint('Google provider signOut error (ignored): $e');
    }
    await FirebaseAuth.instance.signOut();

    _firstNameController.clear();
    _lastNameController.clear();
    _genderController.clear();
    _bloodTypeController.clear();
    _selectedDateOfBirth = null;
    _phoneController.clear();
    for (final c in _conditionControllers) c.dispose();
    for (final c in _allergyControllers) c.dispose();
    for (final c in _immunizationControllers) c.dispose();
    _conditionControllers.clear();
    _allergyControllers.clear();
    _immunizationControllers.clear();
    for (final c in _relFirstControllers) c.dispose();
    for (final c in _relLastControllers) c.dispose();
    for (final c in _relTelControllers) c.dispose();
    for (final c in _relOtherControllers) c.dispose();
    _relFirstControllers.clear();
    _relLastControllers.clear();
    _relTelControllers.clear();
    _relOtherControllers.clear();
    _relatives = [];

    if (mounted) {
      setState(() {
        _profileExists = false;
        _consentAccepted = false;
        _googleError = null;
        _isLoading = false;
        _isSaving = false;
        _isGoogleLoading = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('ออกจากระบบเรียบร้อย')),
      );
    }
  }

  Future<void> _signInWithGoogle() async {
    if (_isGoogleLoading) return;
    setState(() {
      _googleError = null;
      _isGoogleLoading = true;
    });
    try {
      final googleSignIn = GoogleSignIn();
      final googleUser = await googleSignIn.signIn();
      if (googleUser == null) {
        setState(() => _isGoogleLoading = false);
        return;
      }
      final googleAuth = await googleUser.authentication;
      final credential = GoogleAuthProvider.credential(
        idToken: googleAuth.idToken,
        accessToken: googleAuth.accessToken,
      );
      await FirebaseAuth.instance.signInWithCredential(credential);
      if (mounted) {
        setState(() => _isGoogleLoading = false);
        _loadProfile();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isGoogleLoading = false;
          // Don't show "popup_closed" when user cancels the Google sign-in window
          final msg = e.toString().toLowerCase();
          if (msg.contains('popup_closed') || msg.contains('canceled') || msg.contains('cancelled')) {
            _googleError = null;
          } else {
            // User-friendly message only (avoid dumping raw exception JSON to UI)
            _googleError = 'เกิดข้อผิดพลาด กรุณาลองอีกครั้ง';
            debugPrint('Google sign-in error: $e');
          }
        });
      }
    }
  }

  @override
  void initState() {
    super.initState();
    _loadProfile();
  }

  @override
  void dispose() {
    _firstNameController.dispose();
    _lastNameController.dispose();
    _genderController.dispose();
    _bloodTypeController.dispose();
    _phoneController.dispose();
    for (final c in _conditionControllers) c.dispose();
    for (final c in _allergyControllers) c.dispose();
    for (final c in _immunizationControllers) c.dispose();
    for (final c in _relFirstControllers) c.dispose();
    for (final c in _relLastControllers) c.dispose();
    for (final c in _relTelControllers) c.dispose();
    for (final c in _relOtherControllers) c.dispose();
    super.dispose();
  }

  void _syncRelativeControllers() {
    while (_relFirstControllers.length < _relatives.length) {
      final i = _relFirstControllers.length;
      _relFirstControllers.add(TextEditingController(text: _relatives[i]['firstName'] ?? ''));
      _relLastControllers.add(TextEditingController(text: _relatives[i]['lastName'] ?? ''));
      _relTelControllers.add(TextEditingController(text: _relatives[i]['tel'] ?? ''));
      _relOtherControllers.add(TextEditingController(text: _relatives[i]['relationshipOther'] ?? ''));
    }
    while (_relFirstControllers.length > _relatives.length) {
      _relFirstControllers.removeLast().dispose();
      _relLastControllers.removeLast().dispose();
      _relTelControllers.removeLast().dispose();
      _relOtherControllers.removeLast().dispose();
    }
  }

  static String _formatBirthdate(DateTime? d) {
    if (d == null) return '';
    return '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  }

  static DateTime? _parseBirthdate(String? s) {
    if (s == null || s.trim().isEmpty) return null;
    return DateTime.tryParse(s.trim());
  }

  static int? _ageFromDate(DateTime? birth) {
    if (birth == null) return null;
    final now = DateTime.now();
    int age = now.year - birth.year;
    if (now.month < birth.month || (now.month == birth.month && now.day < birth.day)) age--;
    return age < 0 ? null : age;
  }

  /// Splits text by newlines or commas into a list of non-empty trimmed strings.
  static List<String> _textToList(String? text) {
    if (text == null || text.trim().isEmpty) return [];
    return text
        .trim()
        .split(RegExp(r'[\n,]+'))
        .map((e) => e.trim())
        .where((e) => e.isNotEmpty)
        .toList();
  }

  /// Joins list to single text (newline-separated for display in form).
  static String _listToText(List<dynamic>? list) {
    if (list == null || list.isEmpty) return '';
    return list.map((e) => e.toString().trim()).where((e) => e.isNotEmpty).join('\n');
  }

  Future<void> _loadProfile() async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) {
      setState(() {
        _isLoading = false;
        _profileExists = false;
        _consentAccepted = false;
      });
      return;
    }

    final firestore = FirebaseFirestore.instance;
    final uid = user.uid;

    try {
      final userDoc = await firestore.collection('users').doc(uid).get();
      if (userDoc.exists && userDoc.data() != null) {
        final d = userDoc.data()!;
        final first = (d['firstName'] as String?)?.trim() ?? '';
        final last = (d['lastName'] as String?)?.trim() ?? '';
        if (first.isNotEmpty || last.isNotEmpty) {
          _firstNameController.text = first;
          _lastNameController.text = last;
        } else {
          final full = (d['fullName'] as String?)?.trim() ?? '';
          final parts = full.split(RegExp(r'\s+'));
          _firstNameController.text = parts.isNotEmpty ? parts.first : '';
          _lastNameController.text = parts.length > 1 ? parts.sublist(1).join(' ') : '';
        }
        _genderController.text = d['gender'] as String? ?? '';
        _selectedDateOfBirth = _parseBirthdate((d['birthdate'] ?? d['dateOfBirth']) as String?);
        _phoneController.text = (d['tel'] ?? d['phone']) as String? ?? '';
        _consentAccepted = d['consentAccepted'] as bool? ?? false;
        _profileExists = true;

        final medRef = firestore.collection('users').doc(uid).collection('medical_histories').doc('current');
        final medDoc = await medRef.get();
        for (final c in _conditionControllers) c.dispose();
        _conditionControllers.clear();
        for (final c in _allergyControllers) c.dispose();
        _allergyControllers.clear();
        if (medDoc.exists && medDoc.data() != null) {
          final m = medDoc.data()!;
          _bloodTypeController.text = m['bloodType'] as String? ?? '';
          final condList = m['medicalCondition'] as List<dynamic>?;
          final allergyList = m['allergies'] as List<dynamic>?;
          for (final x in condList ?? []) {
            _conditionControllers.add(TextEditingController(text: x.toString().trim()));
          }
          for (final x in allergyList ?? []) {
            _allergyControllers.add(TextEditingController(text: x.toString().trim()));
          }
          final immunList = m['immunizations'] as List<dynamic>?;
          for (final c in _immunizationControllers) c.dispose();
          _immunizationControllers.clear();
          for (final x in immunList ?? []) {
            _immunizationControllers.add(TextEditingController(text: x.toString().trim()));
          }
        } else {
          _bloodTypeController.text = '';
          for (final c in _immunizationControllers) c.dispose();
          _immunizationControllers.clear();
        }
        final relSnap = await firestore.collection('users').doc(uid).collection('relatives').get();
        _relatives = relSnap.docs.map((doc) {
          final d = doc.data();
          return {
            'id': doc.id,
            'firstName': d['firstName'] as String? ?? '',
            'lastName': d['lastName'] as String? ?? '',
            'tel': d['tel'] as String? ?? '',
            'relationship': d['relationship'] as String? ?? '',
            'relationshipOther': d['relationshipOther'] as String? ?? '',
          };
        }).toList();
        _syncRelativeControllers();
      } else {
        final profileDoc = await firestore.collection('profiles').doc(uid).get();
        if (profileDoc.exists && profileDoc.data() != null) {
          final d = profileDoc.data()!;
          final full = (d['fullName'] as String?)?.trim() ?? '';
          final parts = full.split(RegExp(r'\s+'));
          _firstNameController.text = parts.isNotEmpty ? parts.first : '';
          _lastNameController.text = parts.length > 1 ? parts.sublist(1).join(' ') : '';
          _genderController.text = d['gender'] as String? ?? '';
          _bloodTypeController.text = d['bloodType'] as String? ?? '';
          _selectedDateOfBirth = _parseBirthdate(d['dateOfBirth'] as String?);
          if (_selectedDateOfBirth == null) _selectedDateOfBirth = _parseBirthdate(d['birthdate'] as String?);
          _phoneController.text = d['phone'] as String? ?? '';
          for (final c in _conditionControllers) c.dispose();
          _conditionControllers.clear();
          for (final s in _textToList(d['underlyingDiseases'] as String?)) {
            _conditionControllers.add(TextEditingController(text: s));
          }
          for (final c in _allergyControllers) c.dispose();
          _allergyControllers.clear();
          for (final s in _textToList(d['drugAllergies'] as String?)) {
            _allergyControllers.add(TextEditingController(text: s));
          }
          for (final c in _immunizationControllers) c.dispose();
          _immunizationControllers.clear();
          _consentAccepted = d['consentAccepted'] as bool? ?? false;
          _profileExists = true;
          _relatives = [];
        } else {
          _profileExists = false;
          _relatives = [];
          _consentAccepted = false;
          _firstNameController.text = user.displayName ?? '';
          _lastNameController.text = '';
          _phoneController.text = user.phoneNumber ?? _phoneController.text;
        }
      }
    } catch (e) {
      debugPrint('Load profile error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('โหลดข้อมูลไม่สำเร็จ กรุณาลองอีกครั้ง')),
        );
      }
    }
    if (mounted) setState(() => _isLoading = false);
  }

  Future<void> _saveProfile() async {
    if (!_consentAccepted) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('โปรดยอมรับข้อตกลงก่อนบันทึกข้อมูล')),
        );
      }
      return;
    }
    if (!(_formKey.currentState?.validate() ?? false)) return;

    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;

    setState(() => _isSaving = true);
    final uid = user.uid;
    final firestore = FirebaseFirestore.instance;

    try {
      final first = _firstNameController.text.trim();
      final last = _lastNameController.text.trim();
      final userPayload = <String, Object?>{
        'firstName': first,
        'lastName': last,
        'fullName': [first, last].where((s) => s.isNotEmpty).join(' '),
        'gender': _genderController.text.trim(),
        'tel': _phoneController.text.trim(),
        'birthdate': _formatBirthdate(_selectedDateOfBirth),
        'age': _ageFromDate(_selectedDateOfBirth)?.toString() ?? '',
        'consentAccepted': true,
        'email': user.email,
        'updatedAt': FieldValue.serverTimestamp(),
      };
      if (!_profileExists) {
        userPayload['createdAt'] = FieldValue.serverTimestamp();
        userPayload['consentAcceptedAt'] = FieldValue.serverTimestamp();
      }

      await firestore.collection('users').doc(uid).set(userPayload, SetOptions(merge: true));

      final conditions = _conditionControllers.map((c) => c.text.trim()).where((s) => s.isNotEmpty).toList();
      final allergies = _allergyControllers.map((c) => c.text.trim()).where((s) => s.isNotEmpty).toList();
      final immunizations = _immunizationControllers.map((c) => c.text.trim()).where((s) => s.isNotEmpty).toList();
      final medicalPayload = <String, Object?>{
        'bloodType': _bloodTypeController.text.trim(),
        'medicalCondition': conditions,
        'allergies': allergies,
        'immunizations': immunizations,
      };
      await firestore
          .collection('users')
          .doc(uid)
          .collection('medical_histories')
          .doc('current')
          .set(medicalPayload, SetOptions(merge: true));

      final relRef = firestore.collection('users').doc(uid).collection('relatives');
      final existingSnap = await relRef.get();
      final currentIds = _relatives.map((r) => r['id']!).where((id) => id.isNotEmpty).toSet();
      for (final doc in existingSnap.docs) {
        if (!currentIds.contains(doc.id)) await doc.reference.delete();
      }
      for (int i = 0; i < _relatives.length; i++) {
        if (i < _relFirstControllers.length && i < _relLastControllers.length && i < _relTelControllers.length) {
          _relatives[i]['firstName'] = _relFirstControllers[i].text.trim();
          _relatives[i]['lastName'] = _relLastControllers[i].text.trim();
          _relatives[i]['tel'] = _relTelControllers[i].text.trim();
        }
        if (i < _relOtherControllers.length) {
          _relatives[i]['relationshipOther'] = _relOtherControllers[i].text.trim();
        }
      }
      for (final r in _relatives) {
        final id = r['id']!;
        final data = {
          'firstName': (r['firstName'] ?? '').trim(),
          'lastName': (r['lastName'] ?? '').trim(),
          'tel': (r['tel'] ?? '').trim(),
          'relationship': (r['relationship'] ?? '').trim(),
          'relationshipOther': (r['relationshipOther'] ?? '').trim(),
        };
        if (id.isEmpty) {
          await relRef.add(data);
        } else {
          await relRef.doc(id).set(data, SetOptions(merge: true));
        }
      }

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('บันทึกข้อมูลเรียบร้อย')),
        );
      }
      if (mounted) {
        setState(() => _profileExists = true);
      }
    } catch (e) {
      debugPrint('Save profile error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('บันทึกไม่สำเร็จ กรุณาลองอีกครั้ง')),
        );
      }
    }
    if (mounted) setState(() => _isSaving = false);
  }

  Future<void> _deleteProfile() async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('ลบข้อมูลส่วนตัว?'),
        content: const Text('การลบนี้จะลบเฉพาะข้อมูลส่วนตัวที่บันทึกไว้ในระบบ แต่จะไม่ลบบัญชี Google ของคุณ'),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('ยกเลิก')),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: FilledButton.styleFrom(backgroundColor: Theme.of(context).colorScheme.error),
            child: const Text('ลบ'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;

    final uid = user.uid;
    final firestore = FirebaseFirestore.instance;
    try {
      await firestore.collection('users').doc(uid).collection('medical_histories').doc('current').delete();
    } catch (_) { /* subcollection doc may not exist */ }
    try {
      final relSnap = await firestore.collection('users').doc(uid).collection('relatives').get();
      for (final doc in relSnap.docs) await doc.reference.delete();
    } catch (_) { /* optional */ }
    try {
      await firestore.collection('users').doc(uid).delete();
    } catch (e) {
      debugPrint('Delete users doc error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('ลบไม่สำเร็จ กรุณาลองอีกครั้ง')),
        );
      }
      return;
    }
    try {
      await firestore.collection('profiles').doc(uid).delete();
    } catch (_) { /* cleanup legacy */ }
    _firstNameController.clear();
    _lastNameController.clear();
    _genderController.clear();
    _bloodTypeController.clear();
    _selectedDateOfBirth = null;
    _phoneController.clear();
    for (final c in _conditionControllers) c.dispose();
    for (final c in _allergyControllers) c.dispose();
    for (final c in _immunizationControllers) c.dispose();
    _conditionControllers.clear();
    _allergyControllers.clear();
    _immunizationControllers.clear();
    for (final c in _relFirstControllers) c.dispose();
    for (final c in _relLastControllers) c.dispose();
    for (final c in _relTelControllers) c.dispose();
    for (final c in _relOtherControllers) c.dispose();
    _relFirstControllers.clear();
    _relLastControllers.clear();
    _relTelControllers.clear();
    _relOtherControllers.clear();
    _relatives = [];

    if (mounted) {
      setState(() => _profileExists = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('ลบข้อมูลส่วนตัวเรียบร้อย')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final appTextTheme = Theme.of(context).textTheme;
    final colorScheme = Theme.of(context).colorScheme;
    const lightBlueBackground = Color(0xFFA9C3D6);

    final isLoggedIn = FirebaseAuth.instance.currentUser != null;
    final user = FirebaseAuth.instance.currentUser;

    if (_isLoading && isLoggedIn) {
      return Scaffold(
        backgroundColor: lightBlueBackground,
        appBar: AppBar(title: const Text('ข้อมูลส่วนตัว')),
        body: const Center(child: CircularProgressIndicator()),
      );
    }

    return Scaffold(
      backgroundColor: lightBlueBackground,
      appBar: AppBar(
        title: const Text('ข้อมูลส่วนตัว'),
        actions: [
          if (isLoggedIn && _profileExists)
            IconButton(
              tooltip: 'ลบข้อมูลส่วนตัว',
              onPressed: _isSaving ? null : _deleteProfile,
              icon: Icon(Icons.delete_outline, color: colorScheme.error),
            ),
        ],
      ),
      bottomNavigationBar: isLoggedIn
          ? SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
                child: FilledButton.icon(
                  onPressed: (_isSaving || !_consentAccepted) ? null : _saveProfile,
                  icon: _isSaving
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Icon(Icons.save_outlined, size: 18),
                  label: const Text('บันทึก'),
                ),
              ),
            )
          : null,
      body: !isLoggedIn
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(24.0),
                child: Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16.0),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          'เข้าสู่ระบบเพื่อบันทึกข้อมูล',
                          textAlign: TextAlign.center,
                          style: appTextTheme.bodyLarge?.copyWith(
                            color: colorScheme.primary,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        if (_googleError != null) ...[
                          const SizedBox(height: 8),
                          Text(
                            _googleError!,
                            style: appTextTheme.bodySmall?.copyWith(color: colorScheme.error),
                            textAlign: TextAlign.center,
                          ),
                        ],
                        const SizedBox(height: 12),
                        FilledButton(
                          onPressed: _isGoogleLoading ? null : _signInWithGoogle,
                          style: FilledButton.styleFrom(
                            padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 28),
                          ),
                          child: _isGoogleLoading
                              ? const SizedBox(
                                  height: 20,
                                  width: 20,
                                  child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                                )
                              : const Text('เข้าสู่ระบบด้วย Google'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            )
          : SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Form(
          key: _formKey,
          child: Column(
            children: [
              if ((user?.email ?? '').isNotEmpty) ...[
                Text(
                  'บัญชี: ${user!.email}',
                  style: appTextTheme.bodySmall?.copyWith(color: Colors.black87),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 4),
                InkWell(
                  onTap: (_isSaving || _isGoogleLoading) ? null : _confirmSignOut,
                  child: Text(
                    'ออกจากระบบ',
                    style: appTextTheme.bodySmall?.copyWith(
                      color: colorScheme.error,
                      fontWeight: FontWeight.w600,
                      decoration: TextDecoration.underline,
                    ),
                    textAlign: TextAlign.center,
                  ),
                ),
                const SizedBox(height: 12),
              ],
              Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Checkbox(
                              value: _consentAccepted,
                              onChanged: (v) => setState(() => _consentAccepted = v ?? false),
                            ),
                            Expanded(
                              child: Padding(
                                padding: const EdgeInsets.only(top: 10),
                                child: Text.rich(
                                  TextSpan(
                                    children: [
                                      TextSpan(
                                        text: 'ฉันได้อ่านและยอมรับข้อตกลงและนโยบายการเก็บรวบรวม ใช้ และเปิดเผยข้อมูลส่วนตัวและข้อมูลสุขภาพ ',
                                        style: appTextTheme.bodySmall?.copyWith(color: Colors.black87),
                                      ),
                                      TextSpan(
                                        text: '(กดเพื่ออ่านรายละเอียด)',
                                        style: appTextTheme.bodySmall?.copyWith(
                                          color: Colors.black87,
                                          fontWeight: FontWeight.w700,
                                          decoration: TextDecoration.underline,
                                        ),
                                        recognizer: TapGestureRecognizer()..onTap = _showConsentDialog,
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                        if (!_consentAccepted)
                          Padding(
                            padding: const EdgeInsets.only(left: 12),
                            child: Text(
                              'ต้องยอมรับก่อนจึงจะบันทึกได้',
                              style: appTextTheme.bodySmall?.copyWith(color: colorScheme.error),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
              if (isLoggedIn) ...[
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    'ข้อมูลส่วนตัวของผู้ใช้งาน',
                    textAlign: TextAlign.center,
                    style: appTextTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.bold,
                      color: Colors.black,
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                const SizedBox(height: 16),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: _buildEditableField(label: 'ชื่อ', controller: _firstNameController),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              child: _buildEditableField(label: 'นามสกุล', controller: _lastNameController),
                            ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        Row(
                          children: [
                            Expanded(child: _buildGenderDropdown()),
                            const SizedBox(width: 12),
                            Expanded(child: _buildBloodTypeDropdown()),
                          ],
                        ),
                        const SizedBox(height: 16),
                        _buildDateOfBirthField(),
                        const SizedBox(height: 16),
                        _buildAgeDisplay(),
                        const SizedBox(height: 16),
                        _buildEditableField(label: 'เบอร์โทร', controller: _phoneController),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                _buildConditionsSection(),
                const SizedBox(height: 16),
                _buildAllergiesSection(),
                const SizedBox(height: 16),
                _buildImmunizationsSection(),
                const SizedBox(height: 24),
                _buildEmergencyContactsSection(),
                const SizedBox(height: 30),
              ],
            ],
          ),
        ),
      ),
    );
  }

  static const List<Map<String, String>> _genderOptions = [
    {'value': '', 'label': '-- เลือก --'},
    {'value': 'MALE', 'label': 'ชาย'},
    {'value': 'FEMALE', 'label': 'หญิง'},
  ];
  static const List<Map<String, String>> _bloodTypeOptions = [
    {'value': '', 'label': '-- เลือก --'},
    {'value': 'A', 'label': 'A'},
    {'value': 'B', 'label': 'B'},
    {'value': 'O', 'label': 'O'},
    {'value': 'AB', 'label': 'AB'},
  ];

  static const List<String> _monthNames = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December',
  ];

  static int _lastDayOfMonth(int year, int month) {
    if (month == 12) return 31;
    return DateTime(year, month + 1, 0).day;
  }

  Future<void> _pickDateOfBirth() async {
    final now = DateTime.now();
    final initial = _selectedDateOfBirth ?? DateTime(now.year - 25, now.month, now.day);
    if (!mounted) return;
    final result = await showDialog<DateTime>(
      context: context,
      builder: (context) => _BirthdatePickerDialog(
        initial: initial,
        maxDate: now,
        monthNames: _monthNames,
        lastDayOfMonth: _lastDayOfMonth,
      ),
    );
    if (result != null && mounted) setState(() => _selectedDateOfBirth = result);
  }

  Widget _buildDateOfBirthField() {
    final appTextTheme = Theme.of(context).textTheme;
    final displayText = _selectedDateOfBirth != null
        ? _formatBirthdate(_selectedDateOfBirth)
        : 'แตะเพื่อเลือกวันเกิด';
    return InkWell(
      onTap: _pickDateOfBirth,
      borderRadius: BorderRadius.circular(4),
      child: InputDecorator(
        decoration: InputDecoration(
          labelText: 'วันเกิด',
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(4)),
          isDense: true,
          contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        ),
        child: Row(
          children: [
            Icon(Icons.calendar_today_outlined, size: 20, color: Theme.of(context).colorScheme.primary),
            const SizedBox(width: 12),
            Text(
              displayText,
              style: appTextTheme.bodyLarge?.copyWith(
                color: _selectedDateOfBirth != null ? Colors.black : Colors.black54,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAgeDisplay() {
    final appTextTheme = Theme.of(context).textTheme;
    final age = _ageFromDate(_selectedDateOfBirth);
    final displayText = age != null ? '$age ปี' : '—';
    return InputDecorator(
      decoration: const InputDecoration(
        labelText: 'อายุ',
        border: OutlineInputBorder(),
        isDense: true,
        contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
      ),
      child: Text(
        displayText,
        style: appTextTheme.bodyLarge?.copyWith(color: Colors.black87),
      ),
    );
  }

  Widget _buildGenderDropdown() {
    final value = _genderController.text.trim();
    final validValue = _genderOptions.any((o) => o['value'] == value) ? value : '';
    return DropdownButtonFormField<String>(
      value: validValue.isEmpty ? null : validValue,
      decoration: const InputDecoration(
        labelText: 'เพศโดยกำเนิด',
        border: OutlineInputBorder(),
        isDense: true,
      ),
      isExpanded: true,
      items: _genderOptions.map((o) {
        return DropdownMenuItem<String>(
          value: o['value']!.isEmpty ? null : o['value'],
          child: Text(o['label']!),
        );
      }).toList(),
      onChanged: (v) {
        _genderController.text = v ?? '';
        setState(() {});
      },
    );
  }

  Widget _buildBloodTypeDropdown() {
    final value = _bloodTypeController.text.trim();
    final validValue = _bloodTypeOptions.any((o) => o['value'] == value) ? value : '';
    return DropdownButtonFormField<String>(
      value: validValue.isEmpty ? null : validValue,
      decoration: const InputDecoration(
        labelText: 'หมู่เลือด',
        border: OutlineInputBorder(),
        isDense: true,
      ),
      isExpanded: true,
      items: _bloodTypeOptions.map((o) {
        return DropdownMenuItem<String>(
          value: o['value']!.isEmpty ? null : o['value'],
          child: Text(o['label']!),
        );
      }).toList(),
      onChanged: (v) {
        _bloodTypeController.text = v ?? '';
        setState(() {});
      },
    );
  }

  Widget _buildEditableField({
    required String label,
    required TextEditingController controller,
  }) {
    return TextField(
      controller: controller,
      maxLines: 1,
      decoration: InputDecoration(
        labelText: label,
        border: const OutlineInputBorder(),
        isDense: true,
      ),
    );
  }

  static const List<Map<String, String>> _relationshipOptions = [
    {'value': '', 'label': '-- เลือก --'},
    {'value': 'MOTHER', 'label': 'แม่'},
    {'value': 'FATHER', 'label': 'พ่อ'},
    {'value': 'SPOUSE', 'label': 'คู่สมรส'},
    {'value': 'CHILD', 'label': 'บุตร'},
    {'value': 'FRIEND', 'label': 'เพื่อน'},
    {'value': 'RELATIVE', 'label': 'ญาติ'},
    {'value': 'OTHER', 'label': 'อื่นๆ'},
  ];

  Widget _buildConditionsSection() {
    final appTextTheme = Theme.of(context).textTheme;
    return SizedBox(
      width: double.infinity,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 4, bottom: 8),
            child: Text(
              'โรคประจำตัว',
              style: appTextTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
                color: Colors.black87,
              ),
            ),
          ),
          ...List.generate(_conditionControllers.length, (i) {
            return Card(
              margin: const EdgeInsets.only(bottom: 12),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _conditionControllers[i],
                        decoration: const InputDecoration(
                          labelText: 'โรคหรือภาวะ',
                          border: OutlineInputBorder(),
                          isDense: true,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton(
                      icon: Icon(Icons.delete_outline, color: Theme.of(context).colorScheme.error),
                      onPressed: () => setState(() {
                        _conditionControllers.removeAt(i).dispose();
                      }),
                    ),
                  ],
                ),
              ),
            );
          }),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              onPressed: () => setState(() => _conditionControllers.add(TextEditingController())),
              icon: const Icon(Icons.add, size: 20),
              label: const Text('เพิ่มโรคประจำตัว'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAllergiesSection() {
    final appTextTheme = Theme.of(context).textTheme;
    return SizedBox(
      width: double.infinity,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 4, bottom: 8),
            child: Text(
              'ยาที่แพ้',
              style: appTextTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
                color: Colors.black87,
              ),
            ),
          ),
          ...List.generate(_allergyControllers.length, (i) {
            return Card(
              margin: const EdgeInsets.only(bottom: 12),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _allergyControllers[i],
                        decoration: const InputDecoration(
                          labelText: 'ยาหรือสาร',
                          border: OutlineInputBorder(),
                          isDense: true,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton(
                      icon: Icon(Icons.delete_outline, color: Theme.of(context).colorScheme.error),
                      onPressed: () => setState(() {
                        _allergyControllers.removeAt(i).dispose();
                      }),
                    ),
                  ],
                ),
              ),
            );
          }),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              onPressed: () => setState(() => _allergyControllers.add(TextEditingController())),
              icon: const Icon(Icons.add, size: 20),
              label: const Text('เพิ่มยาที่แพ้'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildImmunizationsSection() {
    return SizedBox(
      width: double.infinity,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 4, bottom: 8),
            child: Text(
              'ยาที่ดื้อ',
              style: Theme.of(context).textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
                color: Colors.black87,
              ),
            ),
          ),
          ...List.generate(_immunizationControllers.length, (i) {
            return Card(
              margin: const EdgeInsets.only(bottom: 12),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _immunizationControllers[i],
                        decoration: const InputDecoration(
                          labelText: 'ยาหรือสาร',
                          border: OutlineInputBorder(),
                          isDense: true,
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    IconButton(
                      icon: Icon(Icons.delete_outline, color: Theme.of(context).colorScheme.error),
                      onPressed: () => setState(() {
                        _immunizationControllers.removeAt(i).dispose();
                      }),
                    ),
                  ],
                ),
              ),
            );
          }),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              onPressed: () => setState(() => _immunizationControllers.add(TextEditingController())),
              icon: const Icon(Icons.add, size: 20),
              label: const Text('เพิ่มยาที่ดื้อ'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildEmergencyContactsSection() {
    final appTextTheme = Theme.of(context).textTheme;
    return SizedBox(
      width: double.infinity,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 4, bottom: 8),
            child: Text(
              'ผู้ติดต่อฉุกเฉิน',
              style: appTextTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
                color: Colors.black87,
              ),
            ),
          ),
          ...List.generate(_relatives.length, (i) {
          final r = _relatives[i];
          if (i >= _relFirstControllers.length || i >= _relLastControllers.length || i >= _relTelControllers.length) {
            return const SizedBox.shrink();
          }
          return Card(
            margin: const EdgeInsets.only(bottom: 12),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _relFirstControllers[i],
                          decoration: const InputDecoration(
                            labelText: 'ชื่อ',
                            border: OutlineInputBorder(),
                            isDense: true,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: TextField(
                          controller: _relLastControllers[i],
                          decoration: const InputDecoration(
                            labelText: 'นามสกุล',
                            border: OutlineInputBorder(),
                            isDense: true,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _relTelControllers[i],
                    decoration: const InputDecoration(
                      labelText: 'เบอร์โทร',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                    keyboardType: TextInputType.phone,
                  ),
                  const SizedBox(height: 8),
                  DropdownButtonFormField<String>(
                    value: r['relationship'] ?? '',
                    decoration: const InputDecoration(
                      labelText: 'ความสัมพันธ์',
                      border: OutlineInputBorder(),
                      isDense: true,
                    ),
                    items: _relationshipOptions.map((opt) {
                      return DropdownMenuItem(
                        value: opt['value'],
                        child: Text(opt['label']!),
                      );
                    }).toList(),
                    onChanged: (v) => setState(() => _relatives[i]['relationship'] = v ?? ''),
                  ),
                  if ((r['relationship'] ?? '') == 'OTHER') ...[
                    const SizedBox(height: 8),
                    if (i < _relOtherControllers.length)
                      TextField(
                        controller: _relOtherControllers[i],
                        decoration: const InputDecoration(
                          labelText: 'ระบุความสัมพันธ์ (อื่นๆ)',
                          border: OutlineInputBorder(),
                          isDense: true,
                        ),
                      ),
                  ],
                  const SizedBox(height: 4),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton.icon(
                      onPressed: () => setState(() {
                        _relatives.removeAt(i);
                        _relFirstControllers.removeAt(i).dispose();
                        _relLastControllers.removeAt(i).dispose();
                        _relTelControllers.removeAt(i).dispose();
                        _relOtherControllers.removeAt(i).dispose();
                      }),
                      icon: const Icon(Icons.delete_outline, size: 18),
                      label: const Text('ลบ'),
                      style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
                    ),
                  ),
                ],
              ),
            ),
          );
        }),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              onPressed: () => setState(() {
                _relatives.add({
                  'id': '',
                  'firstName': '',
                  'lastName': '',
                  'tel': '',
                  'relationship': '',
                  'relationshipOther': '',
                });
                _relFirstControllers.add(TextEditingController());
                _relLastControllers.add(TextEditingController());
                _relTelControllers.add(TextEditingController());
                _relOtherControllers.add(TextEditingController());
              }),
              icon: const Icon(Icons.add, size: 20),
              label: const Text('เพิ่มผู้ติดต่อฉุกเฉิน'),
            ),
          ),
        ],
      ),
    );
  }
}

class _BirthdatePickerDialog extends StatefulWidget {
  const _BirthdatePickerDialog({
    required this.initial,
    required this.maxDate,
    required this.monthNames,
    required this.lastDayOfMonth,
  });

  final DateTime initial;
  final DateTime maxDate;
  final List<String> monthNames;
  final int Function(int year, int month) lastDayOfMonth;

  @override
  State<_BirthdatePickerDialog> createState() => _BirthdatePickerDialogState();
}

class _BirthdatePickerDialogState extends State<_BirthdatePickerDialog> {
  late int _month;
  late int _year;
  late int _day;

  @override
  void initState() {
    super.initState();
    _month = widget.initial.month;
    _year = widget.initial.year;
    _day = widget.initial.day.clamp(1, widget.lastDayOfMonth(widget.initial.year, widget.initial.month));
  }

  void _clampDay() {
    final last = widget.lastDayOfMonth(_year, _month);
    if (_day > last) setState(() => _day = last);
  }

  @override
  Widget build(BuildContext context) {
    final lastDay = widget.lastDayOfMonth(_year, _month);
    final day = _day.clamp(1, lastDay);
    final now = widget.maxDate;

    return AlertDialog(
      title: const Text('เลือกวันเกิด'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Expanded(
                  child: DropdownButtonFormField<int>(
                    value: _month,
                    decoration: const InputDecoration(labelText: 'เดือน', border: OutlineInputBorder()),
                    items: List.generate(12, (i) => i + 1).map((m) {
                      return DropdownMenuItem(value: m, child: Text(widget.monthNames[m - 1]));
                    }).toList(),
                    onChanged: (v) {
                      if (v != null) {
                        setState(() {
                          _month = v;
                          _clampDay();
                        });
                      }
                    },
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: DropdownButtonFormField<int>(
                    value: _year,
                    decoration: const InputDecoration(labelText: 'ปี', border: OutlineInputBorder()),
                    items: List.generate(now.year - 1900 + 1, (i) => now.year - i).map((y) {
                      return DropdownMenuItem(value: y, child: Text('$y'));
                    }).toList(),
                    onChanged: (v) {
                      if (v != null) {
                        setState(() {
                          _year = v;
                          _clampDay();
                        });
                      }
                    },
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<int>(
              value: day,
              decoration: const InputDecoration(labelText: 'วัน', border: OutlineInputBorder()),
              items: List.generate(lastDay, (i) => i + 1).map((d) {
                return DropdownMenuItem(value: d, child: Text('$d'));
              }).toList(),
              onChanged: (v) {
                if (v != null) setState(() => _day = v);
              },
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('ยกเลิก')),
        FilledButton(
          onPressed: () {
            final d = DateTime(_year, _month, day);
            if (!d.isAfter(now)) Navigator.of(context).pop(d);
          },
          child: const Text('ตกลง'),
        ),
      ],
    );
  }
}
