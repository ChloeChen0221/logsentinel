#!/bin/bash
# End-to-End Pipeline Verification Script
# This script validates the complete alert pipeline from log generation to notification

set -e

# 默认参数
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
LOKI_URL="${LOKI_URL:-http://localhost:3102}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-600}"

# 计数器
TESTS_PASSED=0
TESTS_FAILED=0

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# 辅助函数
write_step() {
    echo -e "\n${CYAN}>>> $1${NC}"
}

write_success() {
    echo -e "  ${GREEN}✓ $1${NC}"
    ((TESTS_PASSED++))
}

write_failure() {
    echo -e "  ${RED}✗ $1${NC}"
    ((TESTS_FAILED++))
}

write_info() {
    echo -e "  ${YELLOW}→ $1${NC}"
}

test_service_health() {
    local url=$1
    local service_name=$2
    
    if curl -s --connect-timeout 5 "${url}/health" > /dev/null 2>&1; then
        write_success "$service_name is healthy"
        return 0
    else
        write_failure "$service_name is not accessible"
        return 1
    fi
}

wait_for_pod_ready() {
    local pod_name=$1
    local namespace=$2
    local timeout_sec=${3:-120}
    
    write_info "Waiting for pod $pod_name to be ready..."
    local elapsed=0
    while [ $elapsed -lt $timeout_sec ]; do
        local status=$(kubectl get pod "$pod_name" -n "$namespace" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
        if [ "$status" = "Running" ]; then
            sleep 5  # 等待日志开始输出
            write_success "Pod $pod_name is running"
            return 0
        fi
        sleep 2
        ((elapsed+=2))
    done
    write_failure "Pod $pod_name failed to start within $timeout_sec seconds"
    return 1
}

create_test_rule() {
    local backend_url=$1
    
    local rule_data='{
        "name": "E2E Test ERROR Alert",
        "enabled": true,
        "severity": "high",
        "selector_namespace": "demo",
        "selector_labels": null,
        "match_type": "contains",
        "match_pattern": "ERROR",
        "window_seconds": 0,
        "threshold": 1,
        "group_by": ["namespace", "pod"],
        "cooldown_seconds": 60
    }'
    
    local response
    response=$(curl -s -X POST "${backend_url}/api/rules" \
        -H "Content-Type: application/json" \
        -d "$rule_data" 2>/dev/null)
    
    if [ $? -eq 0 ]; then
        local rule_id=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)
        if [ -n "$rule_id" ]; then
            write_success "Rule created with ID: $rule_id"
            echo "$rule_id"
            return 0
        fi
    fi
    write_failure "Failed to create rule"
    return 1
}

wait_for_alert() {
    local backend_url=$1
    local rule_id=$2
    local timeout_sec=${3:-120}
    
    write_info "Waiting for alert to be generated (timeout: ${timeout_sec}s)..."
    local elapsed=0
    while [ $elapsed -lt $timeout_sec ]; do
        local response
        response=$(curl -s "${backend_url}/api/alerts?rule_id=${rule_id}" 2>/dev/null)
        
        if [ $? -eq 0 ]; then
            local count=$(echo "$response" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('items', [])))" 2>/dev/null)
            if [ "$count" -gt 0 ]; then
                local alert_id=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['items'][0]['id'])" 2>/dev/null)
                local hit_count=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin)['items'][0]['hit_count'])" 2>/dev/null)
                write_success "Alert generated: ID=$alert_id, Hit Count=$hit_count"
                echo "$response"
                return 0
            fi
        fi
        
        sleep 5
        ((elapsed+=5))
        echo -n "."
    done
    echo ""
    write_failure "No alert generated within $timeout_sec seconds"
    return 1
}

cleanup_test_resources() {
    local backend_url=$1
    local rule_id=$2
    
    write_step "Cleaning up test resources..."
    
    # 删除测试 pod
    kubectl delete pod error-log-generator -n demo --ignore-not-found=true 2>/dev/null || true
    
    # 删除规则
    if [ -n "$rule_id" ]; then
        if curl -s -X DELETE "${backend_url}/api/rules/${rule_id}" > /dev/null 2>&1; then
            write_success "Rule deleted"
        else
            write_failure "Failed to delete rule"
        fi
    fi
}

# 主执行流程
echo -e "${CYAN}=== End-to-End Pipeline Verification ===${NC}"
echo "Backend URL: $BACKEND_URL"
echo "Loki URL: $LOKI_URL"
echo "Timeout: ${TIMEOUT_SECONDS}s"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Step 1: 检查前置条件
write_step "Step 1/8: Checking prerequisites"

if kubectl version --client &>/dev/null; then
    write_success "kubectl is available"
else
    write_failure "kubectl not found"
    exit 1
fi

if minikube status &>/dev/null; then
    write_success "Minikube is running"
else
    write_failure "Minikube is not running"
    exit 1
fi

# Step 2: 检查服务健康状态
write_step "Step 2/8: Checking services health"

if ! test_service_health "$BACKEND_URL" "Backend API"; then
    echo -e "\n${YELLOW}Please start the backend service:${NC}"
    echo "  cd backend"
    echo "  python -m backend.main"
    exit 1
fi

# 检查 Loki
if curl -s --connect-timeout 5 "${LOKI_URL}/ready" > /dev/null 2>&1; then
    write_success "Loki is ready"
else
    write_failure "Loki is not accessible"
    echo -e "\n${YELLOW}Please ensure Loki port-forward is running:${NC}"
    echo "  kubectl port-forward -n loki svc/loki 3102:3100"
    exit 1
fi

# Step 3: 创建 demo namespace
write_step "Step 3/8: Creating demo namespace"
kubectl create namespace demo --dry-run=client -o yaml | kubectl apply -f - 2>/dev/null
write_success "Namespace 'demo' ready"

# Step 4: 部署测试 pod
write_step "Step 4/8: Deploying test pod"
TEST_POD_PATH="${SCRIPT_DIR}/test-pod.yaml"
if [ ! -f "$TEST_POD_PATH" ]; then
    write_failure "test-pod.yaml not found at $TEST_POD_PATH"
    exit 1
fi

kubectl delete pod error-log-generator -n demo --ignore-not-found=true 2>/dev/null || true
sleep 2
kubectl apply -f "$TEST_POD_PATH"

if ! wait_for_pod_ready "error-log-generator" "demo" 60; then
    write_failure "Test pod deployment failed"
    exit 1
fi

# Step 5: 验证 Loki 中的日志
write_step "Step 5/8: Verifying logs in Loki"
write_info "Waiting 15 seconds for logs to be scraped by Promtail..."
sleep 15

QUERY='%7Bnamespace%3D%22demo%22%7D'  # URL encoded: {namespace="demo"}
LOKI_RESPONSE=$(curl -s "${LOKI_URL}/loki/api/v1/query_range?query=${QUERY}&limit=10" 2>/dev/null)

if [ $? -eq 0 ]; then
    RESULT_COUNT=$(echo "$LOKI_RESPONSE" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('data', {}).get('result', [])))" 2>/dev/null || echo "0")
    if [ "$RESULT_COUNT" -gt 0 ]; then
        write_success "Logs found in Loki"
        
        # 检查 ERROR 关键字
        if echo "$LOKI_RESPONSE" | grep -q "ERROR"; then
            write_success "ERROR keyword found in logs"
        else
            write_failure "ERROR keyword not found in logs"
        fi
    else
        write_failure "No logs found in Loki for namespace 'demo'"
        write_info "Please check Promtail is running and scraping logs"
        cleanup_test_resources "$BACKEND_URL" ""
        exit 1
    fi
else
    write_failure "Failed to query Loki"
    cleanup_test_resources "$BACKEND_URL" ""
    exit 1
fi

# Step 6: 创建告警规则
write_step "Step 6/8: Creating alert rule"
RULE_ID=$(create_test_rule "$BACKEND_URL")
if [ -z "$RULE_ID" ] || [ "$RULE_ID" = "" ]; then
    write_failure "Rule creation failed"
    cleanup_test_resources "$BACKEND_URL" ""
    exit 1
fi

# Step 7: 等待告警生成
write_step "Step 7/8: Waiting for alert generation"
write_info "The engine runs every 30 seconds. This may take up to 2 minutes..."
ALERT_RESPONSE=$(wait_for_alert "$BACKEND_URL" "$RULE_ID" "$TIMEOUT_SECONDS")
if [ -z "$ALERT_RESPONSE" ]; then
    write_failure "Alert was not generated"
    write_info "Check backend logs for engine execution details"
    cleanup_test_resources "$BACKEND_URL" "$RULE_ID"
    exit 1
fi

# 验证告警详情
ALERT_SEVERITY=$(echo "$ALERT_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['items'][0]['severity'])" 2>/dev/null || echo "")
if [ "$ALERT_SEVERITY" = "high" ]; then
    write_success "Alert severity is correct: high"
else
    write_failure "Alert severity mismatch: expected 'high', got '$ALERT_SEVERITY'"
fi

FIRST_ALERT_ID=$(echo "$ALERT_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['items'][0]['id'])" 2>/dev/null)
FIRST_HIT_COUNT=$(echo "$ALERT_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['items'][0]['hit_count'])" 2>/dev/null)

# Step 8: 验证告警更新
write_step "Step 8/8: Verifying alert updates"
write_info "Waiting 45 seconds for alert to be updated..."
sleep 45

UPDATED_ALERT=$(curl -s "${BACKEND_URL}/api/alerts/${FIRST_ALERT_ID}" 2>/dev/null)
if [ $? -eq 0 ]; then
    UPDATED_HIT_COUNT=$(echo "$UPDATED_ALERT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('hit_count', 0))" 2>/dev/null || echo "0")
    if [ "$UPDATED_HIT_COUNT" -gt "$FIRST_HIT_COUNT" ]; then
        write_success "Alert hit count increased: $FIRST_HIT_COUNT → $UPDATED_HIT_COUNT"
    else
        write_failure "Alert hit count did not increase"
    fi
else
    write_failure "Failed to fetch updated alert"
fi

# 清理
cleanup_test_resources "$BACKEND_URL" "$RULE_ID"

# 总结
echo -e "\n${CYAN}=== Verification Complete ===${NC}"
echo -e "${GREEN}Tests Passed: $TESTS_PASSED${NC}"
if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}Tests Failed: $TESTS_FAILED${NC}"
    echo -e "\n${GREEN}✓ All tests passed! The alert pipeline is working correctly.${NC}"
    exit 0
else
    echo -e "${RED}Tests Failed: $TESTS_FAILED${NC}"
    echo -e "\n${RED}✗ Some tests failed. Please check the errors above.${NC}"
    exit 1
fi
