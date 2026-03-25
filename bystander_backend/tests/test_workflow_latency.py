import asyncio
import time
import unittest

from bystander_backend.agents.agents import ByStanderWorkflow
from bystander_backend.agents.llm_agent import GuidanceAgent, ScriptAgent


class _FakeLlm:
    def __init__(self):
        self.last_user_prompt = ""

    def generate_json(self, model_name, system_prompt, user_prompt, default, temperature=0.1):
        self.last_user_prompt = user_prompt
        return dict(default)


class WorkflowLatencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_prime_support_context_runs_in_parallel(self):
        workflow = ByStanderWorkflow()

        def slow_profile(_user_id):
            time.sleep(0.2)
            return {'firstName': 'Amy'}

        def slow_network(_user_id):
            time.sleep(0.2)
            return {'owner': {}, 'friends': []}

        def slow_facilities(*_args, **_kwargs):
            time.sleep(0.2)
            return []

        workflow.profile_service.get_user_profile = slow_profile
        workflow.profile_service.get_medical_network = slow_network
        workflow.map_agent.run = slow_facilities

        started = time.perf_counter()
        result = await workflow._prime_support_context(
            caller_user_id='caller',
            target_user_id='target',
            scenario='test',
            severity='moderate',
            facility_type='clinic',
            latitude=13.75,
            longitude=100.5,
        )
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.45)
        self.assertIn('patient_profile', result)
        self.assertIn('medical_network', result)

    async def test_find_facilities_async_handles_null_gps(self):
        workflow = ByStanderWorkflow()
        result = await workflow.find_facilities_async({'scenario': 'เจ็บหน้าอก'})
        self.assertEqual(result['total'], 0)
        self.assertTrue(result['pending_location'])

    async def test_run_async_skips_medical_fetch_when_no_history(self):
        workflow = ByStanderWorkflow()
        workflow._triage_async = lambda scenario: WorkflowLatencyTests._awaitable({
            'is_emergency': True,
            'severity': 'moderate',
            'facility_type': 'clinic',
            'reason_th': '',
        })
        workflow._retrieve_rag_async = lambda scenario, severity: WorkflowLatencyTests._awaitable((
            {'source': 'none', 'count': 0},
            'context',
        ))
        workflow.guidance_agent.run = lambda scenario, severity, rag_context, medical_context=None: {
            'guidance': 'test guidance',
            'facility_type': 'clinic',
        }

        async def should_not_run(*args, **kwargs):
            raise AssertionError('_prime_support_context should not run without medical history')

        workflow._prime_support_context = should_not_run
        result = await workflow.run_async({
            'scenario': 'เจ็บหน้าอก',
            'caller_user_id': 'caller-1',
            'target_user_id': 'target-1',
            'medical_context': {
                'individuals': [
                    {
                        'uid': 'target-1',
                        'name': 'Target',
                        'relationship': 'friend',
                        'conditions': [],
                        'allergies': [],
                        'immunizations': [],
                    }
                ]
            }
        })
        self.assertEqual(result['guidance'], 'test guidance')

    @staticmethod
    async def _awaitable(value):
        return value


class PromptInjectionTests(unittest.TestCase):
    def test_script_prompt_includes_relationship_pronoun_and_history(self):
        agent = ScriptAgent(_FakeLlm())
        prompt = agent._build_user_prompt(
            scenario='ผู้ป่วยหายใจลำบาก',
            guidance='โทร 1669',
            user_profile={'firstName': 'Nok'},
            location_context='ใกล้ตลาด',
            latitude=None,
            longitude=None,
            caller_profile=None,
            patient_relationship='แม่',
            patient_pronoun='she',
            patient_medical_history=['asthma'],
        )
        self.assertIn("user's แม่", prompt)
        self.assertIn('referred to as she', prompt)
        self.assertIn('Their known medical history: asthma', prompt)
        self.assertIn('include one short line about known conditions', prompt)

    def test_rag_miss_triggers_search_fallback_context(self):
        agent = GuidanceAgent(_FakeLlm())
        agent._search_condition_guidance = lambda condition: f'{condition} summary'
        context, triggered = agent._build_web_fallback_context(
            rag_context='context about burns only',
            medical_context={
                'individuals': [
                    {
                        'name': 'Amy',
                        'conditions': ['asthma'],
                        'allergies': [],
                        'relationship': 'self',
                    }
                ]
            },
        )
        self.assertEqual(triggered, ['asthma'])
        self.assertIn('asthma summary', context)

    def test_empty_medical_context_does_not_expand_prompt(self):
        agent = GuidanceAgent(_FakeLlm())
        prompt = agent._format_medical_context_prompt({
            'individuals': [
                {
                    'name': 'Amy',
                    'relationship': 'self',
                    'conditions': [],
                    'allergies': [],
                    'immunizations': [],
                }
            ]
        })
        self.assertEqual(prompt, '')


if __name__ == '__main__':
    unittest.main()
