from pipeline import build_customer_pipeline


def test_customer_pipeline_uses_deployment_partition_setting():
    assert build_customer_pipeline().num_partitions == 16
