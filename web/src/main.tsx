import { createRoot } from 'react-dom/client';
import HostedAccess from './HostedAccess';
import './style.css';

const root = document.getElementById('root');
if (!root) throw new Error('Application root is missing');
createRoot(root).render(<HostedAccess />);
