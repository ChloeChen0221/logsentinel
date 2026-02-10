#!/bin/bash
# Setup Loki and Promtail in Minikube
# This script deploys Loki and Promtail using Helm

set -e

# 解析参数
SKIP_NAMESPACE=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-namespace) SKIP_NAMESPACE=true; shift ;;
        --force) FORCE=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

echo -e "${CYAN}=== Loki Stack Deployment Script ===${NC}"

# [1/6] 检查前置条件
echo -e "\n${YELLOW}[1/6] Checking prerequisites...${NC}"

# 检查 minikube
if ! minikube status &>/dev/null; then
    echo -e "${RED}Error: Minikube is not running${NC}"
    echo -e "${YELLOW}Please start Minikube first: minikube start${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Minikube is running${NC}"

# 检查 helm
if ! helm version --short &>/dev/null; then
    echo -e "${RED}Error: Helm is not installed${NC}"
    echo -e "${YELLOW}Please install Helm: brew install helm${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Helm is installed${NC}"

# 检查 kubectl
if ! kubectl version --client &>/dev/null; then
    echo -e "${RED}Error: kubectl not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ kubectl is installed${NC}"

# [2/6] 创建 loki namespace
echo -e "\n${YELLOW}[2/6] Creating namespace...${NC}"
if [ "$SKIP_NAMESPACE" = false ]; then
    kubectl create namespace loki --dry-run=client -o yaml | kubectl apply -f -
    echo -e "${GREEN}✓ Namespace 'loki' ready${NC}"
fi

# [3/6] 添加 Grafana Helm repo
echo -e "\n${YELLOW}[3/6] Adding Grafana Helm repository...${NC}"
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
echo -e "${GREEN}✓ Helm repo added${NC}"

# [4/6] 部署 Loki
echo -e "\n${YELLOW}[4/6] Deploying Loki...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOKI_VALUES_PATH="${SCRIPT_DIR}/../k8s-deployment/loki-values.yaml"

if [ ! -f "$LOKI_VALUES_PATH" ]; then
    echo -e "${RED}Error: Loki values file not found at $LOKI_VALUES_PATH${NC}"
    exit 1
fi

HELM_CMD="helm upgrade --install loki grafana/loki -n loki -f \"$LOKI_VALUES_PATH\" --wait --timeout 10m"
if [ "$FORCE" = true ]; then
    HELM_CMD="$HELM_CMD --force"
fi

echo -e "${GRAY}  This may take 5-10 minutes...${NC}"
eval $HELM_CMD
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Loki deployment failed${NC}"
    echo -e "${YELLOW}  Check logs: kubectl logs -n loki -l app.kubernetes.io/name=loki${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Loki deployed successfully${NC}"

# [5/6] 部署 Promtail
echo -e "\n${YELLOW}[5/6] Deploying Promtail...${NC}"
PROMTAIL_VALUES_PATH="${SCRIPT_DIR}/../k8s-deployment/promtail-values.yaml"

if [ ! -f "$PROMTAIL_VALUES_PATH" ]; then
    echo -e "${RED}Error: Promtail values file not found at $PROMTAIL_VALUES_PATH${NC}"
    exit 1
fi

HELM_CMD="helm upgrade --install promtail grafana/promtail -n loki -f \"$PROMTAIL_VALUES_PATH\" --wait --timeout 5m"
if [ "$FORCE" = true ]; then
    HELM_CMD="$HELM_CMD --force"
fi

eval $HELM_CMD
if [ $? -ne 0 ]; then
    echo -e "${RED}Error: Promtail deployment failed${NC}"
    echo -e "${YELLOW}  Check logs: kubectl logs -n loki -l app.kubernetes.io/name=promtail${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Promtail deployed successfully${NC}"

# [6/6] 验证部署
echo -e "\n${YELLOW}[6/6] Verifying deployment...${NC}"
sleep 5

LOKI_PODS=$(kubectl get pods -n loki -l app.kubernetes.io/name=loki -o jsonpath='{.items[*].status.phase}')
PROMTAIL_PODS=$(kubectl get pods -n loki -l app.kubernetes.io/name=promtail -o jsonpath='{.items[*].status.phase}')

if [[ "$LOKI_PODS" =~ "Running" ]]; then
    echo -e "${GREEN}✓ Loki pods are running${NC}"
else
    echo -e "${YELLOW}⚠ Loki pods status: $LOKI_PODS${NC}"
fi

if [[ "$PROMTAIL_PODS" =~ "Running" ]]; then
    echo -e "${GREEN}✓ Promtail pods are running${NC}"
else
    echo -e "${YELLOW}⚠ Promtail pods status: $PROMTAIL_PODS${NC}"
fi

# 显示后续步骤
echo -e "\n${CYAN}=== Deployment Complete ===${NC}"
echo -e "\n${YELLOW}To access Loki, run:${NC}"
echo -e "  kubectl port-forward -n loki svc/loki-gateway 3100:80"
echo -e "\n${YELLOW}Then test Loki API:${NC}"
echo -e "  curl http://localhost:3100/ready"
echo -e "\n${YELLOW}To view logs:${NC}"
echo -e "  kubectl logs -n loki -l app.kubernetes.io/name=loki -f"
echo -e "  kubectl logs -n loki -l app.kubernetes.io/name=promtail -f"
