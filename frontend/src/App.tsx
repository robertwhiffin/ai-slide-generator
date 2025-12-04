import { AppLayout } from './components/Layout/AppLayout';
import './index.css';
import { SelectionProvider } from './contexts/SelectionContext';
import { ProfileProvider } from './contexts/ProfileContext';
import { SessionProvider } from './contexts/SessionContext';

function App() {
  return (
    <ProfileProvider>
      <SessionProvider>
        <SelectionProvider>
          <AppLayout />
        </SelectionProvider>
      </SessionProvider>
    </ProfileProvider>
  );
}

export default App;
