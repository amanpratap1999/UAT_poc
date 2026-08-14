from agent.capabilities.registry import CapabilityRegistry
from agent.skills.change.skill import ChangeSkill
from agent.skills.incident.skill import IncidentSkill


def test_registry_initialization():
    registry = CapabilityRegistry()
    assert registry._skills == {}
    assert registry._module_map == {}


def test_register_and_discover_skills():
    registry = CapabilityRegistry()

    incident_skill = IncidentSkill()
    registry.register(incident_skill, incident_skill.get_capability_definition())

    change_skill = ChangeSkill()
    registry.register(change_skill, change_skill.get_capability_definition())

    # Find by Name
    assert isinstance(registry.get_skill_by_name("incident"), IncidentSkill)
    assert isinstance(registry.get_skill_by_name("change"), ChangeSkill)

    # Find by Table/Module
    assert isinstance(registry.get_skill_for_module("incident"), IncidentSkill)
    assert isinstance(registry.get_skill_for_module("incident_task"), IncidentSkill)
    assert isinstance(registry.get_skill_for_module("change_request"), ChangeSkill)
    assert isinstance(registry.get_skill_for_module("change_task"), ChangeSkill)


def test_unknown_capability():
    registry = CapabilityRegistry()
    assert registry.get_skill_by_name("problem") is None
    assert registry.get_skill_for_module("problem_task") is None


def test_capability_metadata():
    registry = CapabilityRegistry()
    change_skill = ChangeSkill()
    registry.register(change_skill, change_skill.get_capability_definition())

    definition = registry.get_definition("change")
    assert definition is not None
    assert definition.name == "Change"
    assert "change_request" in definition.supported_tables
