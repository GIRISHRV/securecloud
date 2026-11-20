from backend.catalog import STACK_DEFINITIONS, catalog_response, stack_definition


def test_stack_graphs_reference_only_services_in_the_same_definition():
    for stack in STACK_DEFINITIONS:
        service_ids = {service.id for service in stack.services}
        assert len(service_ids) == len(stack.services)
        for service in stack.services:
            assert service.id not in service.dependencies
            assert set(service.dependencies) <= service_ids


def test_catalog_response_is_a_fresh_allowlisted_view():
    first = catalog_response()
    first["stacks"][0]["services"].clear()
    second = catalog_response()

    assert len(second["stacks"][0]["services"]) == 12
    assert stack_definition("retail-stack") is STACK_DEFINITIONS[0]
    assert stack_definition("unknown") is None


def test_vendor_stack_is_a_validated_bounded_three_service_graph():
    vendor = stack_definition("facilities-vendor-stack")
    assert vendor is not None
    assert vendor.status == "validated"
    assert [(item.id, item.template) for item in vendor.services] == [
        ("vendor-web", "web"),
        ("vendor-api", "api"),
        ("vendor-database", "database"),
    ]
