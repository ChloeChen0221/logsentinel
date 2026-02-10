import { Routes, Route, Navigate, Link, useLocation } from 'react-router-dom'
import { Layout, Menu } from 'antd'
import {
  AppstoreOutlined,
  AlertOutlined,
} from '@ant-design/icons'
import RuleList from './pages/RuleList'
import RuleForm from './pages/RuleForm'
import AlertList from './pages/AlertList'
import AlertDetail from './pages/AlertDetail'

const { Header, Content } = Layout

function App() {
  const location = useLocation()

  const getSelectedKey = () => {
    if (location.pathname.startsWith('/rules')) {
      return 'rules'
    }
    if (location.pathname.startsWith('/alerts')) {
      return 'alerts'
    }
    return 'rules'
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center' }}>
        <div style={{ color: 'white', fontSize: '20px', fontWeight: 'bold', marginRight: '40px' }}>
          LogSentinel
      </div>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[getSelectedKey()]}
          style={{ flex: 1, minWidth: 0 }}
        >
          <Menu.Item key="rules" icon={<AppstoreOutlined />}>
            <Link to="/rules">规则管理</Link>
          </Menu.Item>
          <Menu.Item key="alerts" icon={<AlertOutlined />}>
            <Link to="/alerts">告警列表</Link>
          </Menu.Item>
        </Menu>
      </Header>
      <Content style={{ padding: '24px' }}>
        <Routes>
          <Route path="/" element={<Navigate to="/rules" replace />} />
          <Route path="/rules" element={<RuleList />} />
          <Route path="/rules/new" element={<RuleForm />} />
          <Route path="/rules/:id/edit" element={<RuleForm />} />
          <Route path="/alerts" element={<AlertList />} />
          <Route path="/alerts/:id" element={<AlertDetail />} />
        </Routes>
      </Content>
    </Layout>
  )
}

export default App
