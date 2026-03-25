import 'dart:async';

import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import 'package:permission_handler/permission_handler.dart';
import 'package:bystander_frontend/services/api_service.dart';
import 'package:bystander_frontend/services/friend_name_lookup.dart';
import 'package:bystander_frontend/services/medical_context_cache_service.dart';
import 'package:bystander_frontend/services/offline_first_aid_catalog_service.dart';
import 'package:bystander_frontend/screens/comprehensive_guidance_screen.dart';
import 'package:bystander_frontend/screens/general_first_aid_screen.dart';
import 'package:bystander_frontend/screens/general_info_screen.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:geolocator/geolocator.dart';
import 'package:url_launcher/url_launcher.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late stt.SpeechToText _speech;
  bool _isListening = false;
  String _voiceInputText = 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
  String _status = '';
  final ApiService _apiService = ApiService();
  bool _isLoading = false;

  /// If true, emergency profile data comes from selected friend; otherwise from own account.
  bool _promptForFriend = false;
  bool _loadingFriends = false;
  final List<_HomeFriendOption> _friendOptions = [];
  String? _selectedFriendUid;

  /// Rebuild when Firebase restores session (often async on web); [currentUser] is null on first frame.
  StreamSubscription<User?>? _authSubscription;

  final TextEditingController _textEditingController = TextEditingController();
  final Color microphoneColor =
      Colors.redAccent; // User specified color for mic button
  final Color microphoneListeningColor =
      const Color(0xFF36536B); // User specified this for listening state

  @override
  void initState() {
    super.initState();
    _speech = stt.SpeechToText();
    _loadFriends();
    _authSubscription =
        FirebaseAuth.instance.authStateChanges().listen((User? user) {
      if (!mounted) return;
      setState(() {});
      if (user != null) {
        _loadFriends();
      }
    });
  }

  Future<void> _loadFriends() async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;
    setState(() => _loadingFriends = true);
    try {
      final snap = await FirebaseFirestore.instance
          .collection('users')
          .doc(user.uid)
          .collection('friends')
          .get();
      final list = await Future.wait(
        snap.docs.map((d) async {
          final data = d.data();
          var first = (data['otherFirstName'] as String?)?.trim() ?? '';
          var last = (data['otherLastName'] as String?)?.trim() ?? '';
          final email = (data['otherEmail'] as String?)?.trim() ?? '';
          if (email.isNotEmpty) {
            final lookup = await lookupNameFromUserLookup(email);
            if (first.isEmpty) first = lookup['firstName'] ?? '';
            if (last.isEmpty) last = lookup['lastName'] ?? '';
          }
          final label = formatFriendListLabel(first, last, email);
          return _HomeFriendOption(
            uid: d.id,
            label: label,
            relationship: (data['relationship'] as String?)?.trim() ?? '',
          );
        }),
      );
      if (!mounted) return;
      setState(() {
        _friendOptions
          ..clear()
          ..addAll(list);
        if (_selectedFriendUid != null &&
            !_friendOptions.any((f) => f.uid == _selectedFriendUid)) {
          _selectedFriendUid = null;
        }
      });
    } catch (_) {
      // Friends list is optional for "self" mode.
    } finally {
      if (mounted) setState(() => _loadingFriends = false);
    }
  }

  @override
  void dispose() {
    _authSubscription?.cancel();
    _textEditingController.dispose();
    _speech.cancel();
    super.dispose();
  }

  void _listen() async {
    if (_isListening) return;

    if (kIsWeb) {
      await _startListening();
      return;
    }

    final microphoneStatus = await Permission.microphone.request();
    if (microphoneStatus.isGranted) {
      await _startListening();
    } else {
      setState(() => _status = 'ไม่ได้รับอนุญาตให้ใช้ไมโครโฟน');
    }
  }

  Future<void> _startListening() async {
    final available = await _speech.initialize(
      onStatus: (val) {
        debugPrint('onStatus: $val');
        if (val == 'notListening' || val == 'done') {
          setState(() => _isListening = false);
          if (_voiceInputText.isNotEmpty &&
              _voiceInputText != 'กำลังฟัง...' &&
              _voiceInputText != 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด') {
            _fetchGuidance(_voiceInputText);
          }
        }
      },
      onError: (val) {
        debugPrint('onError: $val');
        setState(() {
          _isListening = false;
          _status = 'เกิดข้อผิดพลาดในการฟัง: ${val.errorMsg}';
        });
      },
    );
    if (available) {
      setState(() => _isListening = true);
      _speech.listen(
        onResult: (val) => setState(() {
          _voiceInputText = val.recognizedWords;
          _textEditingController.text = val.recognizedWords;
          if (val.recognizedWords.isNotEmpty) _status = '';
        }),
        localeId: 'th_TH',
        listenFor: const Duration(seconds: 30),
        pauseFor: const Duration(seconds: 5),
      );
      setState(() {
        _voiceInputText = 'กำลังฟัง...';
        _textEditingController.clear();
        _status = '';
      });
    } else {
      setState(() {
        _status = "ไม่สามารถเข้าถึงไมโครโฟนได้";
        _isListening = false;
      });
    }
  }

  void _stopListening() {
    if (_isListening) {
      _speech.stop();
      setState(() => _isListening = false);
    }
  }

  Future<void> _callEmergencyNumber([String number = '1669']) async {
    final launchUri = Uri(scheme: 'tel', path: number);
    if (await canLaunchUrl(launchUri)) {
      await launchUrl(launchUri);
      return;
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('ไม่สามารถโทรออกไปยัง $number ได้')),
    );
  }

  Future<Position?> _resolveCurrentPosition() async {
    try {
      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        return null;
      }
      return Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.high,
        timeLimit: const Duration(seconds: 8),
      );
    } catch (_) {
      return null;
    }
  }

  Future<void> _fetchGuidance(String sentence) async {
    if (sentence.trim().isEmpty ||
        sentence == 'กำลังฟัง...' ||
        sentence == 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด') {
      setState(() {
        _voiceInputText = 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
        _status = 'กรุณาพูดหรือพิมพ์รายละเอียดของเหตุการณ์';
      });
      return;
    }

    setState(() {
      _isLoading = true;
      _status = 'กำลังประมวลผลคำแนะนำ...';
    });
    FocusScope.of(context).unfocus();

    try {
      final user = FirebaseAuth.instance.currentUser;

      String? targetUid;
      if (_promptForFriend) {
        if (user == null) {
          if (mounted) {
            setState(() {
              _status = 'กรุณาเข้าสู่ระบบเพื่อเลือกเพื่อน';
              _isLoading = false;
            });
          }
          return;
        }
        if (_selectedFriendUid == null || _selectedFriendUid!.isEmpty) {
          if (mounted) {
            setState(() {
              _status = 'กรุณาเลือกเพื่อนที่ต้องการขอคำแนะนำให้';
              _isLoading = false;
            });
          }
          return;
        }
        targetUid = _selectedFriendUid;
      } else {
        targetUid = user?.uid;
      }

      final medicalContext = MedicalContextCacheService.instance.buildPayload(
        callerUserId: user?.uid,
        targetUserId: targetUid,
      );
      final effectiveMedicalContext =
          medicalContext.isEmpty ? null : medicalContext;
      final locationFuture = _resolveCurrentPosition();
      final workflowFuture = _apiService.runAgentWorkflow(
        scenario: sentence,
        callerUserId: user?.uid,
        targetUserId: targetUid,
        medicalContext: effectiveMedicalContext,
      );
      final facilitiesFuture = locationFuture.then(
        (position) => _apiService.findNearbyFacilities(
          scenario: sentence,
          latitude: position?.latitude,
          longitude: position?.longitude,
        ),
      );
      final callScriptFuture = locationFuture.then(
        (position) => _apiService.getCallScript(
          scenario: sentence,
          callerUserId: user?.uid,
          targetUserId: targetUid,
          latitude: position?.latitude,
          longitude: position?.longitude,
          medicalContext: effectiveMedicalContext,
        ),
      );

      final workflowResponse = await workflowFuture;
      if (mounted) {
        if (!workflowResponse.isEmergency ||
            workflowResponse.route == 'general_info') {
          Navigator.push(
            context,
            MaterialPageRoute(
              builder: (context) => GeneralInfoScreen(
                scenario: sentence,
                infoText: workflowResponse.generalInfo,
                triageReason: workflowResponse.triageReason,
              ),
            ),
          ).then((_) {
            setState(() {
              _voiceInputText = 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
              _textEditingController.clear();
              _status = '';
              _isLoading = false;
            });
          });
          return;
        }

        Navigator.push(
          context,
          MaterialPageRoute(
            builder: (context) => ComprehensiveGuidanceScreen(
              guidanceText: workflowResponse.guidance,
              originalQuery: sentence,
              severity: workflowResponse.severity == 'moderate'
                  ? 'mild'
                  : workflowResponse.severity,
              facilityType: workflowResponse.facilityType,
              facilities: workflowResponse.facilities,
              callScript: workflowResponse.callScript,
              facilitiesFuture: facilitiesFuture,
              callScriptFuture: callScriptFuture,
            ),
          ),
        ).then((_) {
          setState(() {
            _voiceInputText = 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
            _textEditingController.clear();
            _status = '';
            _isLoading = false;
          });
        });
      }
    } catch (e) {
      if (!mounted) return;
      final navigator = Navigator.of(context);
      final messenger = ScaffoldMessenger.of(context);

      OfflineFirstAidMatch? fallback;
      try {
        fallback = await OfflineFirstAidCatalogService.instance.searchBestMatch(
          sentence,
        );
      } catch (_) {
        fallback = null;
      }
      if (!mounted) return;

      if (fallback != null) {
        final matched = fallback;
        final fallbackSeverity =
            matched.severity == 'moderate' ? 'mild' : matched.severity;
        navigator
            .push(
          MaterialPageRoute(
            builder: (_) => ComprehensiveGuidanceScreen(
              guidanceText: matched.instructions,
              originalQuery: sentence,
              severity: fallbackSeverity,
              facilityType: matched.facilityType,
            ),
          ),
        )
            .then((_) {
          if (!mounted) return;
          setState(() {
            _voiceInputText = 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
            _textEditingController.clear();
            _status = '';
            _isLoading = false;
          });
        });

        messenger.showSnackBar(
          const SnackBar(
            content: Text(
              'เชื่อมต่อระบบหลักไม่ได้ จึงใช้คำแนะนำจากคู่มือปฐมพยาบาลออฟไลน์',
            ),
          ),
        );
        setState(() {
          _status = 'กำลังใช้งานโหมดออฟไลน์';
          _isLoading = false;
        });
        return;
      }

      navigator
          .push(
        MaterialPageRoute(
          builder: (_) => GeneralFirstAidScreen(initialQuery: sentence),
        ),
      )
          .then((_) {
        if (!mounted) return;
        setState(() {
          _voiceInputText = 'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
          _textEditingController.clear();
          _status = '';
          _isLoading = false;
        });
      });
      messenger.showSnackBar(
        const SnackBar(
          content:
              Text('เชื่อมต่อระบบหลักไม่ได้ จึงเปิดคู่มือปฐมพยาบาลออฟไลน์'),
        ),
      );
      setState(() {
        _status = 'กำลังใช้งานโหมดออฟไลน์';
        _isLoading = false;
      });
    }
    // No finally block needed for isLoading if handled in .then and catch
  }

  @override
  Widget build(BuildContext context) {
    final TextTheme appTextTheme = Theme.of(context).textTheme;
    final ColorScheme appColorScheme = Theme.of(context).colorScheme;
    // Use live auth state (listener above forces rebuild when session restores).
    final bool isLoggedIn = FirebaseAuth.instance.currentUser != null;

    return Scaffold(
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFFFDECEA),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: const Color(0xFFE35D5B)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.warning_amber_rounded,
                            color: Color(0xFFB42318)),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'ถ้าผู้ป่วยหมดสติ ไม่หายใจ หรือเลือดออกมาก ให้โทร 1669 ทันที',
                            style: appTextTheme.titleSmall?.copyWith(
                              fontWeight: FontWeight.w700,
                              color: const Color(0xFF7A271A),
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 10),
                    ElevatedButton.icon(
                      onPressed: () => _callEmergencyNumber('1669'),
                      icon: const Icon(Icons.call),
                      label: const Text('โทร 1669 ตอนนี้'),
                      style: ElevatedButton.styleFrom(
                        minimumSize: const Size(double.infinity, 52),
                        backgroundColor: const Color(0xFFB42318),
                        foregroundColor: Colors.white,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              Card(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'เล่าเหตุการณ์สั้นๆ แล้วกดส่ง',
                        style: appTextTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: appColorScheme.primary,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        'ระบบจะสรุปขั้นตอนฉุกเฉินแบบทีละข้อเพื่อให้ทำตามได้ง่าย',
                        style: appTextTheme.bodyMedium?.copyWith(
                          color: appTextTheme.bodyMedium?.color
                              ?.withValues(alpha: 0.8),
                        ),
                      ),
                      if (isLoggedIn) ...[
                        const SizedBox(height: 12),
                        Text(
                          _promptForFriend
                              ? 'ระบบจะใช้ข้อมูลโปรไฟล์/ประวัติตามเพื่อนที่เลือกในการช่วยสร้างคำแนะนำ'
                              : 'ระบบจะใช้ข้อมูลจากบัญชีของคุณ',
                          style: appTextTheme.bodySmall?.copyWith(
                            color: appTextTheme.bodySmall?.color
                                ?.withValues(alpha: 0.75),
                          ),
                        ),
                        const SizedBox(height: 8),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            FilterChip(
                              label: const Text('ตัวเอง'),
                              selected: !_promptForFriend,
                              onSelected: (_) {
                                setState(() => _promptForFriend = false);
                              },
                            ),
                            FilterChip(
                              label: const Text('เพื่อนในรายชื่อ'),
                              selected: _promptForFriend,
                              onSelected: (_) {
                                setState(() => _promptForFriend = true);
                                _loadFriends();
                              },
                            ),
                          ],
                        ),
                      ],
                      SizedBox(
                        height: (isLoggedIn && _promptForFriend) ? 6 : 14,
                      ),
                      if (isLoggedIn && _promptForFriend) ...[
                        if (_loadingFriends)
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 8),
                            child: LinearProgressIndicator(),
                          )
                        else if (_friendOptions.isEmpty)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              'ยังไม่มีเพื่อน — ไปที่ข้อมูลส่วนตัว แล้วเปิด "รายชื่อเพื่อน" เพื่อเพิ่มเพื่อน',
                              style: appTextTheme.bodySmall?.copyWith(
                                color: appColorScheme.error,
                              ),
                            ),
                          )
                        else
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Text(
                                'เลือกเพื่อน',
                                style: appTextTheme.labelMedium?.copyWith(
                                  color: appTextTheme.bodySmall?.color
                                      ?.withValues(alpha: 0.75),
                                ),
                              ),
                              const SizedBox(height: 6),
                              Theme(
                                data: Theme.of(context).copyWith(
                                  visualDensity: VisualDensity.compact,
                                  materialTapTargetSize:
                                      MaterialTapTargetSize.shrinkWrap,
                                ),
                                child: InputDecorator(
                                  decoration: InputDecoration(
                                    isDense: true,
                                    contentPadding: const EdgeInsets.symmetric(
                                      horizontal: 12,
                                      vertical: 4,
                                    ),
                                    border: OutlineInputBorder(
                                      borderRadius: BorderRadius.circular(10),
                                    ),
                                  ),
                                  child: DropdownButtonHideUnderline(
                                    child: DropdownButton<String>(
                                      isDense: true,
                                      isExpanded: true,
                                      padding: EdgeInsets.zero,
                                      value: _selectedFriendUid,
                                      hint: const Text('แตะเพื่อเลือก'),
                                      items: _friendOptions
                                          .map(
                                            (f) => DropdownMenuItem<String>(
                                              value: f.uid,
                                              child: Text(
                                                f.label,
                                                overflow: TextOverflow.ellipsis,
                                              ),
                                            ),
                                          )
                                          .toList(),
                                      onChanged: (v) => setState(
                                        () => _selectedFriendUid = v,
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                            ],
                          ),
                      ],
                      const SizedBox(height: 14),
                      TextField(
                        controller: _textEditingController,
                        decoration: InputDecoration(
                          hintText: 'ตัวอย่าง: พ่อหมดสติ ไม่หายใจ อยู่หน้าบ้าน',
                          filled: true,
                          fillColor: appColorScheme.surfaceContainerHighest
                              .withValues(alpha: 0.5),
                          enabledBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(10),
                            borderSide: BorderSide(
                              color: appColorScheme.outline
                                  .withValues(alpha: 0.35),
                            ),
                          ),
                          suffixIcon: _textEditingController.text.isNotEmpty
                              ? IconButton(
                                  icon: Icon(Icons.clear,
                                      color: appColorScheme.primary
                                          .withValues(alpha: 0.7)),
                                  onPressed: () {
                                    _textEditingController.clear();
                                    setState(() {
                                      _voiceInputText =
                                          'กดปุ่มไมโครโฟนค้างไว้ เพื่อพูด';
                                    });
                                  },
                                )
                              : null,
                        ),
                        style: appTextTheme.bodyLarge,
                        minLines: 2,
                        maxLines: 4,
                        textInputAction: TextInputAction.done,
                        onSubmitted: (value) {
                          if (value.trim().isNotEmpty) {
                            _fetchGuidance(value.trim());
                          }
                        },
                      ),
                      const SizedBox(height: 12),
                      ElevatedButton.icon(
                        icon: const Icon(Icons.send),
                        label: const Text('ส่งเพื่อขอขั้นตอนช่วยเหลือ'),
                        onPressed: _isLoading
                            ? null
                            : () {
                                if (_textEditingController.text
                                    .trim()
                                    .isNotEmpty) {
                                  _fetchGuidance(
                                      _textEditingController.text.trim());
                                } else {
                                  setState(() {
                                    _status =
                                        'กรุณาพิมพ์รายละเอียดของเหตุการณ์';
                                  });
                                }
                              },
                        style: ElevatedButton.styleFrom(
                          minimumSize: const Size(double.infinity, 52),
                        ),
                      ),
                      const SizedBox(height: 8),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.menu_book_outlined),
                        label: const Text('เปิดคู่มือปฐมพยาบาลออฟไลน์'),
                        onPressed: () {
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (context) =>
                                  const GeneralFirstAidScreen(),
                            ),
                          );
                        },
                        style: OutlinedButton.styleFrom(
                          minimumSize: const Size(double.infinity, 48),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 14),
              Card(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
                  child: Column(
                    children: [
                      Text(
                        _voiceInputText,
                        style: appTextTheme.bodyLarge?.copyWith(
                          fontStyle: FontStyle.italic,
                          color: appTextTheme.bodyLarge?.color
                              ?.withValues(alpha: 0.85),
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 14),
                      _isLoading && !_isListening
                          ? Center(
                              child: CircularProgressIndicator(
                                valueColor: AlwaysStoppedAnimation<Color>(
                                  appColorScheme.primary,
                                ),
                              ),
                            )
                          : GestureDetector(
                              onLongPress: _listen,
                              onLongPressUp: _stopListening,
                              child: Container(
                                padding: const EdgeInsets.all(16),
                                decoration: BoxDecoration(
                                  color: _isListening
                                      ? microphoneListeningColor
                                      : microphoneColor,
                                  shape: BoxShape.circle,
                                  boxShadow: [
                                    BoxShadow(
                                      color:
                                          Colors.black.withValues(alpha: 0.2),
                                      spreadRadius: 1,
                                      blurRadius: 5,
                                      offset: const Offset(0, 3),
                                    ),
                                  ],
                                ),
                                child: Icon(
                                  _isListening ? Icons.mic_off : Icons.mic,
                                  color: Colors.white,
                                  size: 52,
                                ),
                              ),
                            ),
                      const SizedBox(height: 12),
                      Text(
                        _isListening
                            ? 'กำลังฟัง...'
                            : (_isLoading ? _status : 'กดค้างเพื่อพูด'),
                        textAlign: TextAlign.center,
                        style: appTextTheme.bodyMedium?.copyWith(
                          color: appTextTheme.bodyMedium?.color
                              ?.withValues(alpha: 0.75),
                        ),
                      ),
                      if (_status.isNotEmpty && !_isLoading && !_isListening)
                        Padding(
                          padding: const EdgeInsets.only(top: 10),
                          child: Text(
                            _status,
                            style: appTextTheme.bodySmall
                                ?.copyWith(color: appColorScheme.error),
                            textAlign: TextAlign.center,
                          ),
                        ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }
}

class _HomeFriendOption {
  final String uid;
  final String label;
  final String relationship;
  _HomeFriendOption({
    required this.uid,
    required this.label,
    this.relationship = '',
  });
}
