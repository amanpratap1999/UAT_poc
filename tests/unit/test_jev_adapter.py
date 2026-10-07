"""Unit tests for JEV Adapter and Decision Provider."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.decision.provider import (
    Assertion,
    AssertionOperator,
    AssertionResult,
    DecisionProvider,
    VerificationDecision,
    VerificationRequest,
    VerificationResponse,
)
from agent.decision.jev_adapter import JEVAdapter


class MockDecisionProvider(DecisionProvider):
    """Mock decision provider for testing."""
    
    def __init__(self, response: VerificationResponse):
        self._response = response
        self._name = "mock"
        self._available = True
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    async def verify(self, request: VerificationRequest) -> VerificationResponse:
        return self._response
    
    async def decide(self, request: VerificationRequest) -> VerificationResponse:
        return self._response


@pytest.fixture
def sample_verification_request() -> VerificationRequest:
    """Sample verification request for testing."""
    return VerificationRequest(
        task="Verify ServiceNow incident creation",
        expected={
            "record_created": True,
            "priority": "2",
            "state": "In Progress"
        },
        observed={
            "record_created": True,
            "priority": "2",
            "state": "In Progress"
        },
        assertions=[
            Assertion(name="priority", operator=AssertionOperator.EQUALS, expected="2", field_path="priority"),
            Assertion(name="state", operator=AssertionOperator.EQUALS, expected="In Progress", field_path="state"),
        ],
    )


@pytest.fixture
def pass_response() -> VerificationResponse:
    """Mock PASS response."""
    return VerificationResponse(
        decision=VerificationDecision.PASS,
        confidence=0.98,
        reason="All expected conditions were satisfied",
        assertions=[
            AssertionResult(
                assertion=Assertion(name="priority", operator=AssertionOperator.EQUALS, expected="2"),
                observed="2",
                result=VerificationDecision.PASS,
                reason="Values match",
                confidence=0.98,
            ),
            AssertionResult(
                assertion=Assertion(name="state", operator=AssertionOperator.EQUALS, expected="In Progress"),
                observed="In Progress",
                result=VerificationDecision.PASS,
                reason="Values match",
                confidence=0.98,
            ),
        ],
    )


@pytest.fixture
def fail_response() -> VerificationResponse:
    """Mock FAIL response."""
    return VerificationResponse(
        decision=VerificationDecision.FAIL,
        confidence=0.95,
        reason="Priority mismatch",
        assertions=[
            AssertionResult(
                assertion=Assertion(name="priority", operator=AssertionOperator.EQUALS, expected="2"),
                observed="3",
                result=VerificationDecision.FAIL,
                reason="Expected 2, got 3",
                confidence=0.95,
            ),
            AssertionResult(
                assertion=Assertion(name="state", operator=AssertionOperator.EQUALS, expected="In Progress"),
                observed="In Progress",
                result=VerificationDecision.PASS,
                reason="Values match",
                confidence=0.98,
            ),
        ],
    )


@pytest.fixture
def error_response() -> VerificationResponse:
    """Mock VERIFICATION_ERROR response."""
    return VerificationResponse(
        decision=VerificationDecision.VERIFICATION_ERROR,
        confidence=0.0,
        reason="JEV is not configured or unavailable",
        error="JEV_UNAVAILABLE",
    )


class TestDecisionProviderAbstraction:
    """Test the DecisionProvider abstraction works correctly."""
    
    @pytest.mark.asyncio
    async def test_pass_response(self, sample_verification_request: VerificationRequest, pass_response: VerificationResponse):
        """Test that PASS response is handled correctly."""
        provider = MockDecisionProvider(pass_response)
        response = await provider.verify(sample_verification_request)
        
        assert response.is_pass is True
        assert response.is_fail is False
        assert response.is_error is False
        assert response.decision == VerificationDecision.PASS
        assert len(response.assertions) == 2
        assert all(a.result == VerificationDecision.PASS for a in response.assertions)
    
    @pytest.mark.asyncio
    async def test_fail_response(self, sample_verification_request: VerificationRequest, fail_response: VerificationResponse):
        """Test that FAIL response is handled correctly."""
        provider = MockDecisionProvider(fail_response)
        response = await provider.verify(sample_verification_request)
        
        assert response.is_pass is False
        assert response.is_fail is True
        assert response.is_error is False
        assert response.decision == VerificationDecision.FAIL
        assert any(a.result == VerificationDecision.FAIL for a in response.assertions)
    
    @pytest.mark.asyncio
    async def test_error_response(self, sample_verification_request: VerificationRequest, error_response: VerificationResponse):
        """Test that VERIFICATION_ERROR response is handled correctly."""
        provider = MockDecisionProvider(error_response)
        response = await provider.verify(sample_verification_request)
        
        assert response.is_pass is False
        assert response.is_fail is False
        assert response.is_error is True
        assert response.decision == VerificationDecision.VERIFICATION_ERROR
        assert response.error == "JEV_UNAVAILABLE"
    
    @pytest.mark.asyncio
    async def test_decide_alias(self, sample_verification_request: VerificationRequest, pass_response: VerificationResponse):
        """Test that decide() is an alias for verify()."""
        provider = MockDecisionProvider(pass_response)
        response = await provider.decide(sample_verification_request)
        
        assert response.is_pass is True
        assert response.decision == VerificationDecision.PASS


class TestJEVAdapter:
    """Test the JEV Adapter implementation."""
    
    def test_disabled_by_default(self):
        """Test JEV is disabled by default."""
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = False
            adapter = JEVAdapter()
            assert adapter.is_available is False
            assert adapter.name == "jev"
    
    def test_enabled_with_config(self):
        """Test JEV initializes when enabled with config."""
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = True
            mock_settings.return_value.jev.model = "test-model"
            mock_settings.return_value.jev.endpoint = "https://api.test.com/v1"
            mock_settings.return_value.jev.api_key = "test-key"
            mock_settings.return_value.jev.timeout = 30.0
            
            with patch('agent.decision.jev_adapter.AsyncOpenAI'):
                adapter = JEVAdapter()
                assert adapter.is_available is True
    
    def test_missing_model_config(self):
        """Test JEV fails clearly when model config is missing."""
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = True
            mock_settings.return_value.jev.model = ""
            mock_settings.return_value.jev.endpoint = "https://api.test.com/v1"
            mock_settings.return_value.jev.api_key = "test-key"
            
            adapter = JEVAdapter()
            assert adapter.is_available is False
    
    def test_missing_endpoint_config(self):
        """Test JEV fails clearly when endpoint config is missing."""
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = True
            mock_settings.return_value.jev.model = "test-model"
            mock_settings.return_value.jev.endpoint = ""
            mock_settings.return_value.jev.api_key = "test-key"
            
            adapter = JEVAdapter()
            assert adapter.is_available is False
    
    def test_missing_api_key_config(self):
        """Test JEV fails clearly when api_key config is missing."""
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = True
            mock_settings.return_value.jev.model = "test-model"
            mock_settings.return_value.jev.endpoint = "https://api.test.com/v1"
            mock_settings.return_value.jev.api_key = ""
            
            adapter = JEVAdapter()
            assert adapter.is_available is False


class TestJEVVerificationLogic:
    """Test JEV verification logic with mocked responses."""
    
    @pytest.mark.asyncio
    async def test_verify_pass(self, sample_verification_request: VerificationRequest, pass_response: VerificationResponse):
        """Test JEV verify returns PASS when all assertions pass."""
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = True
            mock_settings.return_value.jev.model = "test-model"
            mock_settings.return_value.jev.endpoint = "https://api.test.com/v1"
            mock_settings.return_value.jev.api_key = "test-key"
            mock_settings.return_value.jev.timeout = 30.0
            
            with patch('agent.decision.jev_adapter.AsyncOpenAI') as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value = mock_client
                
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = '{"decision": "PASS", "confidence": 0.98, "reason": "All passed", "assertions": []}'
                mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
                
                adapter = JEVAdapter()
                response = await adapter.verify(sample_verification_request)
                
                assert response.decision == VerificationDecision.PASS
                assert response.confidence == 0.98
    
    @pytest.mark.asyncio
    async def test_verify_fail(self, sample_verification_request: VerificationRequest, fail_response: VerificationResponse):
        """Test JEV verify returns FAIL when any assertion fails."""
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = True
            mock_settings.return_value.jev.model = "test-model"
            mock_settings.return_value.jev.endpoint = "https://api.test.com/v1"
            mock_settings.return_value.jev.api_key = "test-key"
            mock_settings.return_value.jev.timeout = 30.0
            
            with patch('agent.decision.jev_adapter.AsyncOpenAI') as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value = mock_client
                
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = '{"decision": "FAIL", "confidence": 0.95, "reason": "Priority mismatch", "assertions": [{"name": "priority", "expected": "2", "observed": "3", "result": "FAIL", "reason": "Expected 2, got 3", "confidence": 0.95}]}'
                mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
                
                adapter = JEVAdapter()
                response = await adapter.verify(sample_verification_request)
                
                assert response.decision == VerificationDecision.FAIL
                assert len(response.assertions) == 1
                assert response.assertions[0].result == VerificationDecision.FAIL
    
    @pytest.mark.asyncio
    async def test_verify_unavailable_when_disabled(self, sample_verification_request: VerificationRequest):
        """Test JEV verify returns VERIFICATION_ERROR when disabled."""
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = False
            
            adapter = JEVAdapter()
            response = await adapter.verify(sample_verification_request)
            
            assert response.decision == VerificationDecision.VERIFICATION_ERROR
            assert response.error == "JEV_UNAVAILABLE"
    
    @pytest.mark.asyncio
    async def test_verify_timeout(self, sample_verification_request: VerificationRequest):
        """Test JEV verify handles timeout correctly."""
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = True
            mock_settings.return_value.jev.model = "test-model"
            mock_settings.return_value.jev.endpoint = "https://api.test.com/v1"
            mock_settings.return_value.jev.api_key = "test-key"
            mock_settings.return_value.jev.timeout = 0.001  # Very short timeout
            
            with patch('agent.decision.jev_adapter.AsyncOpenAI') as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value = mock_client
                
                async def slow_response(*args, **kwargs):
                    import asyncio
                    await asyncio.sleep(1)
                    return MagicMock()
                
                mock_client.chat.completions.create = slow_response
                
                adapter = JEVAdapter()
                response = await adapter.verify(sample_verification_request)
                
                assert response.decision == VerificationDecision.VERIFICATION_ERROR
                assert response.error == "TIMEOUT"
    
    @pytest.mark.asyncio
    async def test_verify_malformed_response(self, sample_verification_request: VerificationRequest):
        """Test JEV verify handles malformed JSON response."""
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = True
            mock_settings.return_value.jev.model = "test-model"
            mock_settings.return_value.jev.endpoint = "https://api.test.com/v1"
            mock_settings.return_value.jev.api_key = "test-key"
            mock_settings.return_value.jev.timeout = 30.0
            
            with patch('agent.decision.jev_adapter.AsyncOpenAI') as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value = mock_client
                
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = "This is not valid JSON"
                mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
                
                adapter = JEVAdapter()
                response = await adapter.verify(sample_verification_request)
                
                assert response.decision == VerificationDecision.VERIFICATION_ERROR
                assert response.error == "JSON_DECODE_ERROR"
    
    @pytest.mark.asyncio
    async def test_multiple_assertions_all_pass(self):
        """Test JEV with multiple assertions all passing."""
        request = VerificationRequest(
            task="Verify multiple fields",
            expected={"priority": "2", "state": "In Progress", "assignment_group": "Network"},
            observed={"priority": "2", "state": "In Progress", "assignment_group": "Network"},
            assertions=[
                Assertion(name="priority", operator=AssertionOperator.EQUALS, expected="2"),
                Assertion(name="state", operator=AssertionOperator.EQUALS, expected="In Progress"),
                Assertion(name="assignment_group", operator=AssertionOperator.EQUALS, expected="Network"),
            ],
        )
        
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = True
            mock_settings.return_value.jev.model = "test-model"
            mock_settings.return_value.jev.endpoint = "https://api.test.com/v1"
            mock_settings.return_value.jev.api_key = "test-key"
            mock_settings.return_value.jev.timeout = 30.0
            
            with patch('agent.decision.jev_adapter.AsyncOpenAI') as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value = mock_client
                
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = '''{
                    "decision": "PASS",
                    "confidence": 0.99,
                    "reason": "All assertions passed",
                    "assertions": [
                        {"name": "priority", "expected": "2", "observed": "2", "result": "PASS", "reason": "Match", "confidence": 1.0},
                        {"name": "state", "expected": "In Progress", "observed": "In Progress", "result": "PASS", "reason": "Match", "confidence": 1.0},
                        {"name": "assignment_group", "expected": "Network", "observed": "Network", "result": "PASS", "reason": "Match", "confidence": 1.0}
                    ]
                }'''
                mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
                
                adapter = JEVAdapter()
                response = await adapter.verify(request)
                
                assert response.decision == VerificationDecision.PASS
                assert len(response.assertions) == 3
                assert all(a.result == VerificationDecision.PASS for a in response.assertions)
    
    @pytest.mark.asyncio
    async def test_multiple_assertions_one_fails(self):
        """Test JEV with multiple assertions where one fails -> overall FAIL."""
        request = VerificationRequest(
            task="Verify multiple fields",
            expected={"priority": "2", "state": "In Progress"},
            observed={"priority": "3", "state": "In Progress"},
            assertions=[
                Assertion(name="priority", operator=AssertionOperator.EQUALS, expected="2"),
                Assertion(name="state", operator=AssertionOperator.EQUALS, expected="In Progress"),
            ],
        )
        
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = True
            mock_settings.return_value.jev.model = "test-model"
            mock_settings.return_value.jev.endpoint = "https://api.test.com/v1"
            mock_settings.return_value.jev.api_key = "test-key"
            mock_settings.return_value.jev.timeout = 30.0
            
            with patch('agent.decision.jev_adapter.AsyncOpenAI') as mock_client_class:
                mock_client = AsyncMock()
                mock_client_class.return_value = mock_client
                
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = '''{
                    "decision": "FAIL",
                    "confidence": 0.95,
                    "reason": "Priority mismatch",
                    "assertions": [
                        {"name": "priority", "expected": "2", "observed": "3", "result": "FAIL", "reason": "Expected 2, got 3", "confidence": 0.95},
                        {"name": "state", "expected": "In Progress", "observed": "In Progress", "result": "PASS", "reason": "Match", "confidence": 1.0}
                    ]
                }'''
                mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
                
                adapter = JEVAdapter()
                response = await adapter.verify(request)
                
                assert response.decision == VerificationDecision.FAIL
                assert len(response.assertions) == 2
                assert response.assertions[0].result == VerificationDecision.FAIL
                assert response.assertions[1].result == VerificationDecision.PASS


class TestJEVAdapterIntegration:
    """Integration tests for JEV adapter with existing verification flow."""
    
    @pytest.mark.asyncio
    async def test_jev_disabled_mode_preserves_existing_behavior(self):
        """Test that when JEV is disabled, it doesn't interfere with existing flow."""
        with patch('agent.decision.jev_adapter.get_settings') as mock_settings:
            mock_settings.return_value.jev.enabled = False
            
            adapter = JEVAdapter()
            assert adapter.is_available is False
            
            # Verify returns error but doesn't crash
            request = VerificationRequest(task="test")
            response = await adapter.verify(request)
            
            assert response.decision == VerificationDecision.VERIFICATION_ERROR
            assert response.error == "JEV_UNAVAILABLE"
    
    @pytest.mark.asyncio
    async def test_jev_integration_with_orchestrator(self):
        """Test JEV adapter can be imported and used by orchestrator."""
        from agent.cognition.orchestrator import CognitiveOrchestrator
        
        # Verify the import works and JEVAdapter is accessible
        from agent.decision.jev_adapter import JEVAdapter
        assert JEVAdapter is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])