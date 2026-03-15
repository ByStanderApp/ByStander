import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;

class GeneralFirstAidScreen extends StatefulWidget {
  final String initialQuery;

  const GeneralFirstAidScreen({
    super.key,
    this.initialQuery = '',
  });

  @override
  State<GeneralFirstAidScreen> createState() => _GeneralFirstAidScreenState();
}

class _GeneralFirstAidScreenState extends State<GeneralFirstAidScreen> {
  bool _isLoading = true;
  List<Map<String, dynamic>> _allItems = [];
  List<Map<String, dynamic>> _visibleItems = [];
  late final TextEditingController _searchController;

  @override
  void initState() {
    super.initState();
    _searchController = TextEditingController(text: widget.initialQuery);
    _loadCatalog();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadCatalog() async {
    try {
      final raw =
          await rootBundle.loadString('assets/general_first_aid_catalog.json');
      final payload = jsonDecode(raw);
      final items = (payload['items'] as List<dynamic>? ?? [])
          .whereType<Map<String, dynamic>>()
          .toList();
      setState(() {
        _allItems = items;
        _isLoading = false;
      });
      _applyFilter(_searchController.text);
    } catch (_) {
      setState(() {
        _allItems = [];
        _visibleItems = [];
        _isLoading = false;
      });
    }
  }

  void _applyFilter(String query) {
    final q = query.trim().toLowerCase();
    if (q.isEmpty) {
      setState(
          () => _visibleItems = List<Map<String, dynamic>>.from(_allItems));
      return;
    }

    final filtered = _allItems.where((item) {
      final caseName = (item['case_name_th'] ?? '').toString().toLowerCase();
      final keywords = (item['keywords'] ?? '').toString().toLowerCase();
      final instructions =
          (item['instructions'] ?? '').toString().toLowerCase();
      return caseName.contains(q) ||
          keywords.contains(q) ||
          instructions.contains(q);
    }).toList();

    setState(() => _visibleItems = filtered);
  }

  List<String> _parseInstructionSteps(String text) {
    final normalized = text.replaceAll('\r', ' ').replaceAll('\n', ' ').trim();
    if (normalized.isEmpty) return [];
    if (RegExp(r'\d+[\.\)]\s+').hasMatch(normalized)) {
      return normalized
          .split(RegExp(r'(?=\d+[\.\)]\s+)'))
          .map((e) => e.replaceFirst(RegExp(r'^\d+[\.\)]\s*'), '').trim())
          .where((e) => e.isNotEmpty)
          .toList();
    }
    return normalized
        .split(RegExp(r'•\s+|\-\s+|\.\s+(?=[ก-๙A-Za-z])'))
        .map((e) => e.trim())
        .where((e) => e.isNotEmpty)
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('คู่มือปฐมพยาบาลออฟไลน์'),
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                Padding(
                  padding: const EdgeInsets.all(12.0),
                  child: TextField(
                    controller: _searchController,
                    onChanged: _applyFilter,
                    decoration: const InputDecoration(
                      hintText: 'ค้นหาอาการหรือสถานการณ์...',
                      prefixIcon: Icon(Icons.search),
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12.0),
                  child: Text(
                    'โหมดออฟไลน์: ใช้ข้อมูลคู่มือจากฐานข้อมูลในเครื่อง หากอาการรุนแรงให้โทร 1669 ทันที',
                    style: textTheme.bodyMedium?.copyWith(
                      color: colorScheme.primary.withValues(alpha: 0.85),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: _visibleItems.isEmpty
                      ? Center(
                          child: Text(
                            'ไม่พบข้อมูลที่ตรงกับการค้นหา',
                            style: textTheme.bodyLarge,
                          ),
                        )
                      : ListView.builder(
                          itemCount: _visibleItems.length,
                          itemBuilder: (context, index) {
                            final item = _visibleItems[index];
                            final title =
                                (item['case_name_th'] ?? 'ไม่ระบุเหตุการณ์')
                                    .toString();
                            final instructions =
                                (item['instructions'] ?? '').toString();
                            final steps = _parseInstructionSteps(instructions);
                            final severity =
                                (item['severity'] ?? 'none').toString();
                            final facilityType =
                                (item['facility_type'] ?? 'none').toString();

                            return Card(
                              margin: const EdgeInsets.symmetric(
                                  horizontal: 12, vertical: 6),
                              child: ExpansionTile(
                                title: Text(
                                  title,
                                  style: textTheme.titleMedium
                                      ?.copyWith(fontWeight: FontWeight.w700),
                                ),
                                subtitle: Text(
                                    'ความรุนแรง: $severity | สถานพยาบาล: $facilityType'),
                                childrenPadding:
                                    const EdgeInsets.fromLTRB(16, 0, 16, 16),
                                expandedCrossAxisAlignment:
                                    CrossAxisAlignment.start,
                                children: [
                                  if (steps.isEmpty)
                                    Text(instructions,
                                        style: textTheme.bodyLarge)
                                  else
                                    Column(
                                      children: List.generate(steps.length,
                                          (stepIndex) {
                                        return Padding(
                                          padding: EdgeInsets.only(
                                            bottom: stepIndex < steps.length - 1
                                                ? 10
                                                : 0,
                                          ),
                                          child: Row(
                                            crossAxisAlignment:
                                                CrossAxisAlignment.start,
                                            children: [
                                              CircleAvatar(
                                                radius: 12,
                                                backgroundColor:
                                                    colorScheme.primary,
                                                child: Text(
                                                  '${stepIndex + 1}',
                                                  style: const TextStyle(
                                                    color: Colors.white,
                                                    fontWeight: FontWeight.bold,
                                                    fontSize: 12,
                                                  ),
                                                ),
                                              ),
                                              const SizedBox(width: 10),
                                              Expanded(
                                                child: Text(
                                                  steps[stepIndex],
                                                  style: textTheme.bodyLarge
                                                      ?.copyWith(height: 1.45),
                                                ),
                                              ),
                                            ],
                                          ),
                                        );
                                      }),
                                    ),
                                ],
                              ),
                            );
                          },
                        ),
                ),
              ],
            ),
    );
  }
}
