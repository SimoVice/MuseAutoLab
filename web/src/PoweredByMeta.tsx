import logo from './meta-logo.png';
import './meta-attribution.css';

export default function PoweredByMeta() {
  return <span className="meta-attribution">Powered by <img src={logo} alt="Meta" width="72" height="18" /></span>;
}
