import { AppLayout } from './components/Layout/AppLayout';
import './index.css';
import { SelectionProvider } from './contexts/SelectionContext';
import { ProfileProvider } from './contexts/ProfileContext';
import { SessionProvider } from './contexts/SessionContext';
import { GenerationProvider } from './contexts/GenerationContext';

function App() {
  return (
    <ProfileProvider>
      <SessionProvider>
        <GenerationProvider>
          <SelectionProvider>
            <AppLayout />
          </SelectionProvider>
        </GenerationProvider>
      </SessionProvider>
    </ProfileProvider>
  );
}

export default App;
