import React, { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import axios from 'axios';

interface ChatMessage {
  role: string;
  content: string;
  metadata?: {
    title?: string;
  };
}

interface ChatInterfaceProps {
  onSlideUpdate: () => void;
}

const ChatContainer = styled.div`
  display: flex;
  flex-direction: column;
  height: 100%;
  flex: 1;
`;

const MessagesContainer = styled.div`
  flex: 1;
  overflow-y: auto;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 20px;
  background: #fafbfc;
  margin-bottom: 20px;
  min-height: 300px;
  max-height: calc(100vh - 300px);
`;

const Message = styled.div<{ $isUser: boolean; $hasMetadata?: boolean }>`
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  align-items: ${props => props.$isUser ? 'flex-end' : 'flex-start'};
`;

const MessageBubble = styled.div<{ $isUser: boolean; $hasMetadata?: boolean }>`
  max-width: 85%;
  padding: 14px 18px;
  border-radius: ${props => props.$isUser ? '20px 20px 6px 20px' : '20px 20px 20px 6px'};
  background: ${props => {
    if (props.$hasMetadata) return '#f8f9fa';
    return props.$isUser ? '#2563eb' : '#ffffff';
  }};
  color: ${props => {
    if (props.$hasMetadata) return '#374151';
    return props.$isUser ? 'white' : '#374151';
  }};
  word-wrap: break-word;
  line-height: 1.5;
  font-size: 14px;
  border: ${props => props.$hasMetadata ? '1px solid #e5e7eb' : props.$isUser ? 'none' : '1px solid #f0f0f0'};
  box-shadow: ${props => props.$hasMetadata ? 'none' : '0 2px 8px rgba(0, 0, 0, 0.08)'};
`;

const MessageMetadata = styled.div`
  font-size: 0.8rem;
  color: #6b7280;
  margin-bottom: 4px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  
  &:hover {
    color: #374151;
  }
`;

const ExpandIcon = styled.span<{ $expanded: boolean }>`
  font-size: 10px;
  transition: transform 0.2s ease;
  transform: ${props => props.$expanded ? 'rotate(90deg)' : 'rotate(0deg)'};
`;

const CollapsibleContent = styled.div<{ $expanded: boolean }>`
  max-height: ${props => props.$expanded ? '200px' : '40px'};
  overflow: hidden;
  transition: max-height 0.3s ease;
  position: relative;
  
  ${props => !props.$expanded && `
    &::after {
      content: '';
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      height: 20px;
      background: linear-gradient(transparent, #f8f9fa);
      pointer-events: none;
    }
  `}
`;

const InputContainer = styled.div`
  display: flex;
  flex-direction: column;
`;

const TextInputWrapper = styled.div`
  position: relative;
  background: white;
  border: 1px solid #d1d5db;
  border-radius: 24px;
  transition: all 0.2s ease;
  display: flex;
  align-items: flex-end;
  padding: 4px 4px 4px 12px;
  gap: 8px;
  
  &:focus-within {
    border-color: #2563eb;
    box-shadow: 0 0 0 1px rgba(37, 99, 235, 0.1);
  }
`;

const LeftActions = styled.div`
  display: flex;
  align-items: center;
  padding-bottom: 8px;
`;

const TextInputArea = styled.div`
  flex: 1;
  display: flex;
  align-items: flex-end;
`;

const TextInput = styled.textarea`
  flex: 1;
  padding: 14px 12px;
  border: none;
  border-radius: 0;
  resize: none;
  min-height: 24px;
  max-height: 200px;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.5;
  outline: none;
  background: transparent;

  &::placeholder {
    color: #9ca3af;
  }
`;

const RightActions = styled.div`
  display: flex;
  gap: 4px;
  align-items: flex-end;
  padding-bottom: 4px;
`;

const IconButton = styled.button<{ $variant?: 'add' | 'voice' }>`
  padding: 6px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 500;
  font-size: 16px;
  transition: all 0.15s ease;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  position: relative;

  ${props => {
    switch (props.$variant) {
      case 'add':
        return `
          background: transparent;
          color: #6b7280;
          font-size: 18px;
          font-weight: 400;
          &:hover:not(:disabled) {
            background: #f3f4f6;
            color: #374151;
          }
        `;
      case 'voice':
        return `
          background: transparent;
          color: #6b7280;
          &:hover:not(:disabled) {
            background: #f3f4f6;
            color: #374151;
          }
        `;
      default:
        return `
          background: transparent;
          color: #6b7280;
          &:hover:not(:disabled) {
            background: #f3f4f6;
            color: #374151;
          }
        `;
    }
  }}

  &:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    transform: none;
  }

  &:active {
    transform: scale(0.95);
  }
`;

const LoadingIndicator = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
  color: #6b7280;
  font-style: italic;
`;

const PlaceholderMessage = styled.div`
  text-align: center;
  color: #9ca3af;
  font-style: italic;
  padding: 40px 20px;
`;

const ChatInterface: React.FC<ChatInterfaceProps> = ({ onSlideUpdate }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('Generate a succinct report EY Parthenon. Do not generate more than 5 slides. Use the information available in your tools. Use visualisations. Include an overview slide of EY Parthenon. Think about your response.');
  const [isLoading, setIsLoading] = useState(false);
  const [lastMessageCount, setLastMessageCount] = useState(0);
  const [expandedMessages, setExpandedMessages] = useState<Set<number>>(new Set());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const pollForUpdates = async () => {
    try {
      console.log('Polling for updates...');
      const response = await axios.get('http://localhost:8000/chat/status/default');
      const newMessages = response.data.messages;
      const newMessageCount = response.data.message_count;
      
      console.log(`Received ${newMessageCount} messages (was ${lastMessageCount})`);
      console.log('Current messages in state:', messages.length);
      
      // Always update if there are new messages
      if (newMessageCount !== lastMessageCount) {
        console.log('Message count changed, updating UI');
        console.log('New messages:', newMessages);
        setMessages([...newMessages]); // Force new array to trigger re-render
        setLastMessageCount(newMessageCount);
        onSlideUpdate(); // Refresh slides when conversation updates
      }
      
      // More relaxed completion detection - only stop if we haven't seen new messages for a while
      const lastMessage = newMessages[newMessages.length - 1];
      let shouldStopPolling = false;
      
      if (newMessages.length > 1 && lastMessage?.role === 'assistant') {
        // Look for a final assistant message that's not a tool message
        const isToolMessage = lastMessage.metadata?.title?.includes('🔧') || 
                             lastMessage.metadata?.title?.includes('tool') ||
                             lastMessage.metadata?.title?.includes('Tool');
        
        console.log(`Last message: role=${lastMessage.role}, hasMetadata=${!!lastMessage.metadata?.title}, isToolMessage=${isToolMessage}`);
        
        // Only stop if it's been a regular assistant message for a few polls
        if (!isToolMessage && !lastMessage.metadata?.title) {
          // Check if message count hasn't changed recently
          if (newMessageCount === lastMessageCount) {
            shouldStopPolling = true;
          }
        }
      }
      
      if (shouldStopPolling) {
        console.log('Conversation appears complete, stopping polling');
        setIsLoading(false);
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      }
    } catch (error: any) {
      console.error('Error polling for updates:', error);
      console.error('Error details:', error.response?.data || error.message);
      // Continue polling on error
    }
  };

  const startPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
    }
    
    // Start polling every 1000ms for real-time feel
    pollingRef.current = setInterval(pollForUpdates, 1000);
    
    // Set a timeout to stop polling after 2 minutes if no completion detected
    setTimeout(() => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
        setIsLoading(false);
      }
    }, 120000); // 2 minutes
  };

  const sendMessage = async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage = inputValue.trim();
    setInputValue('');
    setIsLoading(true);

    try {
      // Send message to backend
      const response = await axios.post('http://localhost:8000/chat', {
        message: userMessage,
        session_id: 'default'
      });

      // Update with immediate response (should include user message)
      setMessages(response.data.messages);
      setLastMessageCount(response.data.messages.length);
      
      // Start polling for real-time updates
      startPolling();
      
    } catch (error) {
      console.error('Error sending message:', error);
      // Add error message to chat
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: 'Sorry, there was an error processing your request. Please try again.',
        metadata: { title: '❌ Error' }
      }]);
      setIsLoading(false);
    }
  };

  // Test function to debug the backend connection
  const testBackendConnection = async () => {
    try {
      console.log('Testing backend connection...');
      const response = await axios.get('http://localhost:8000/health');
      console.log('Backend health check:', response.data);
      
      const statusResponse = await axios.get('http://localhost:8000/chat/status/default');
      console.log('Current conversation status:', statusResponse.data);
      
      // Force update UI with current messages
      setMessages([...statusResponse.data.messages]);
      setLastMessageCount(statusResponse.data.message_count);
    } catch (error: any) {
      console.error('Backend connection test failed:', error);
    }
  };

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const toggleMessageExpansion = (index: number) => {
    const newExpanded = new Set(expandedMessages);
    if (newExpanded.has(index)) {
      newExpanded.delete(index);
    } else {
      newExpanded.add(index);
    }
    setExpandedMessages(newExpanded);
  };

  const renderMessage = (message: ChatMessage, index: number) => {
    const isUser = message.role === 'user';
    const hasMetadata = !!message.metadata?.title;
    const isExpanded = expandedMessages.has(index);
    const isToolMessage = hasMetadata && (
      message.metadata?.title?.includes('🔧') || 
      message.metadata?.title?.includes('tool') ||
      message.metadata?.title?.includes('Tool') ||
      message.metadata?.title?.includes('Using tool')
    );

    return (
      <Message key={index} $isUser={isUser} $hasMetadata={hasMetadata}>
        {hasMetadata && (
          <MessageMetadata onClick={() => isToolMessage && toggleMessageExpansion(index)}>
            {isToolMessage && (
              <ExpandIcon $expanded={isExpanded}>▶</ExpandIcon>
            )}
            {message.metadata?.title}
          </MessageMetadata>
        )}
        <MessageBubble $isUser={isUser} $hasMetadata={hasMetadata}>
          {isToolMessage ? (
            <CollapsibleContent $expanded={isExpanded}>
              {message.content}
            </CollapsibleContent>
          ) : (
            message.content
          )}
        </MessageBubble>
      </Message>
    );
  };

  return (
    <ChatContainer>
      <MessagesContainer>
        {messages.length === 0 ? (
          <PlaceholderMessage>
            💬 Ready to create amazing slides!<br/>
            <span style={{fontSize: '13px', color: '#9ca3af'}}>
              Type your request below to get started
            </span>
          </PlaceholderMessage>
        ) : (
          messages.map(renderMessage)
        )}
        
        {isLoading && (
          <LoadingIndicator>
            <span>🤔 Processing your request...</span>
          </LoadingIndicator>
        )}
        
        <div ref={messagesEndRef} />
      </MessagesContainer>
      
      <InputContainer>
        <TextInputWrapper>
          <LeftActions>
            <IconButton 
              $variant="add"
              disabled={true}
              title="Add files and more (coming soon)"
            >
              +
            </IconButton>
          </LeftActions>
          
          <TextInputArea>
            <TextInput
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Ask anything... (Press Enter to send)"
              disabled={isLoading}
            />
          </TextInputArea>
          
          <RightActions>
            <IconButton 
              $variant="voice"
              disabled={true}
              title="Voice input (coming soon)"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1c-2.2 0-4 1.8-4 4v7c0 2.2 1.8 4 4 4s4-1.8 4-4V5c0-2.2-1.8-4-4-4z"/>
                <path d="M19 10v2c0 3.9-3.1 7-7 7s-7-3.1-7-7v-2"/>
                <line x1="12" y1="19" x2="12" y2="23"/>
                <line x1="8" y1="23" x2="16" y2="23"/>
              </svg>
            </IconButton>
          </RightActions>
        </TextInputWrapper>
      </InputContainer>
    </ChatContainer>
  );
};

export default ChatInterface;
