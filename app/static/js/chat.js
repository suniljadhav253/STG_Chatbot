// app/static/js/chat.js
document.addEventListener('DOMContentLoaded', () => {
    const conversationView = document.getElementById('conversation-view');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-button');
    const CHAT_HISTORY_KEY = 'rxoLogisticsAIChatHistory';
    const MAX_HISTORY_TURNS = 5; // Number of recent Q&A pairs for LLM context

    // Workplace Modal Elements
    const workplaceModal = document.getElementById('workplace-selection-modal');
    const workplaceSelect = document.getElementById('workplace-select');
    const newWorkplaceNameInput = document.getElementById('new-workplace-name');
    const saveToSelectedWorkplaceBtn = document.getElementById('save-to-selected-workplace-btn');
    const cancelWorkplaceSelectionBtn = document.getElementById('cancel-workplace-selection-btn');
    let currentInsightToSave = null; 

    function saveMessages(messages) {
        try {
            localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(messages));
        } catch (e) {
            console.error("Error saving messages to localStorage:", e);
            // Potentially handle quota exceeded error
        }
    }

    function loadMessages() {
        try {
            const storedMessages = localStorage.getItem(CHAT_HISTORY_KEY);
            return storedMessages ? JSON.parse(storedMessages) : [];
        } catch (e) {
            console.error("Error loading messages from localStorage:", e);
            localStorage.removeItem(CHAT_HISTORY_KEY); // Clear corrupted data
            return [];
        }
    }
    
    function renderMessage(messageObj) { 
        addMessage(messageObj.text, messageObj.sender, messageObj.chart, messageObj.table, false, messageObj.id, messageObj.query);
    }
    
    function addMessage(text, sender, chartData = null, tableData = null, shouldSave = true, insightId = null, originalQuery = null) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('message', `${sender}-message`);
        if (sender === 'ai' && (chartData || tableData)) {
            messageDiv.style.position = 'relative';
        }

        let chartContainer = null;
        if (sender === 'ai' && chartData && typeof Chart !== 'undefined') {
            chartContainer = document.createElement('div');
            chartContainer.classList.add('chart-wrapper');
            const chartCanvas = document.createElement('canvas');
            chartContainer.appendChild(chartCanvas);
            messageDiv.appendChild(chartContainer); // Append chart first
            try {
                new Chart(chartCanvas, {
                    type: chartData.type,
                    data: chartData.data,
                    options: chartData.options || { responsive: true, maintainAspectRatio: false, animation: !shouldSave }
                });
            } catch (e) { 
                console.error("Error rendering chart:", e, chartData);
                const errorP = document.createElement('p'); errorP.textContent = "[Chart data invalid or rendering error]"; errorP.style.color = 'red';
                chartContainer.appendChild(errorP);
            }
        } else if (sender === 'ai' && chartData) { 
            const errorP = document.createElement('p'); errorP.textContent = "[Chart.js missing]"; errorP.style.color = 'red';
            messageDiv.appendChild(errorP);
        }

        let tableElementContainer = null;
        if (sender === 'ai' && tableData) {
            tableElementContainer = document.createElement('div');
            tableElementContainer.classList.add('table-container');
            const table = document.createElement('table');
            const thead = document.createElement('thead');
            const tbody = document.createElement('tbody');
            const headerRow = document.createElement('tr');
            tableData.headers.forEach(headerText => { const th = document.createElement('th'); th.textContent = headerText; headerRow.appendChild(th); });
            thead.appendChild(headerRow);
            table.appendChild(thead);
            tableData.rows.forEach(rowData => { const row = document.createElement('tr'); rowData.forEach(cellData => { const td = document.createElement('td'); td.textContent = cellData; row.appendChild(td); }); tbody.appendChild(row); });
            table.appendChild(tbody);
            tableElementContainer.appendChild(table);
            messageDiv.appendChild(tableElementContainer);
        }

        if (text) { 
            const p = document.createElement('p');
            p.classList.add('message-text');
            if (sender === 'ai' && (chartData || tableData)) {
                p.classList.add('explanation-text'); 
            }
            p.textContent = text;
            messageDiv.appendChild(p);
        }

        if (sender === 'ai' && (chartData || tableData) && insightId) {
            const saveBtn = document.createElement('button');
            saveBtn.classList.add('save-to-workplace-btn');
            saveBtn.innerHTML = '&#x271A;'; 
            saveBtn.title = 'Save to Workplace';
            saveBtn.onclick = () => {
                currentInsightToSave = {
                    id: insightId, query: originalQuery || "User query not captured", 
                    type: chartData ? chartData.type : (tableData ? 'table' : 'text'),
                    data: chartData ? chartData.data : (tableData ? { headers: tableData.headers, rows: tableData.rows } : null),
                    options: chartData ? chartData.options : null,
                    summary: text, 
                    timestamp: new Date().toISOString()
                };
                openWorkplaceModal();
            };
            messageDiv.appendChild(saveBtn); 
        }

        conversationView.appendChild(messageDiv);
        if (shouldSave || conversationView.children.length <= loadMessages().length + 1) { // +1 for current message
             conversationView.scrollTop = conversationView.scrollHeight;
        }

        if (shouldSave) {
            const currentMessages = loadMessages();
            currentMessages.push({ text, sender, chart: chartData, table: tableData, id: insightId, query: originalQuery });
            saveMessages(currentMessages);
        }
    }

    async function fetchWorkplaces() {
        try {
            const response = await fetch('/api/workplaces');
            if (!response.ok) throw new Error(`Failed to fetch workplaces: ${response.statusText}`);
            return await response.json();
        } catch (error) {
            console.error("Error fetching workplaces:", error);
            // alert("Could not load workplaces. Please try again."); // Avoid alert if not critical path
            return [];
        }
    }

    async function openWorkplaceModal() {
        const workplaces = await fetchWorkplaces();
        workplaceSelect.innerHTML = '<option value="">-- Select Existing --</option>'; 
        if (workplaces.length > 0) {
            workplaces.forEach(wp => {
                const option = document.createElement('option');
                option.value = wp.id;
                option.textContent = wp.name;
                workplaceSelect.appendChild(option);
            });
        } else {
             workplaceSelect.options[0].textContent = "No workplaces yet. Create one below.";
        }
        newWorkplaceNameInput.value = ''; 
        workplaceModal.style.display = 'block';
    }

    function closeWorkplaceModal() {
        workplaceModal.style.display = 'none';
        currentInsightToSave = null;
    }

    cancelWorkplaceSelectionBtn.addEventListener('click', closeWorkplaceModal);

    saveToSelectedWorkplaceBtn.addEventListener('click', async () => {
        if (!currentInsightToSave) { console.error("No insight data to save."); return; }

        let targetWorkplaceId = workplaceSelect.value;
        const newWorkplaceName = newWorkplaceNameInput.value.trim();

        if (newWorkplaceName) {
            try {
                const response = await fetch('/api/workplaces', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: newWorkplaceName })
                });
                const result = await response.json();
                if (!response.ok) {
                    alert(`Error creating workplace: ${result.error || 'Unknown error'}`); return;
                }
                targetWorkplaceId = result.id;
                alert(`Workplace '${newWorkplaceName}' created.`);
            } catch (error) { alert(`Failed to create workplace: ${error}`); return; }
        } else if (!targetWorkplaceId) {
             alert("Please select an existing workplace or enter a name for a new one."); return;
        }

        try {
            const saveResponse = await fetch(`/api/workplaces/${targetWorkplaceId}/insights`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(currentInsightToSave)
            });
            const saveResult = await saveResponse.json();
            if (!saveResponse.ok) {
                alert(`Error saving insight: ${saveResult.error || 'Unknown error'}`);
            } else {
                alert(`Insight saved to workplace successfully!`);
                closeWorkplaceModal();
            }
        } catch (error) { alert(`Failed to save insight: ${error}`); }
    });

    const initialMessages = loadMessages();
    if (initialMessages.length > 0) {
        initialMessages.forEach(msg => renderMessage(msg));
        conversationView.scrollTop = conversationView.scrollHeight;
    } else { 
        const welcomeMsgEl = document.querySelector('.message.ai-message p.message-text');
        if(welcomeMsgEl && welcomeMsgEl.textContent.includes("Welcome")) {
            saveMessages([{text: welcomeMsgEl.textContent, sender:'ai', chart:null, table:null, id: `welcome_${Date.now()}`, query:'Initial Welcome'}]);
        }
     }

    async function handleUserQuery() {
        const query = userInput.value.trim();
        if (!query) return;
        addMessage(query, 'user', null, null, true, null, query); 
        userInput.value = ''; 
        const thinkingMsgDiv = document.createElement('div');
        thinkingMsgDiv.classList.add('message', 'ai-message', 'thinking');
        thinkingMsgDiv.innerHTML = '<p><span class="thinking-spinner"></span> RXO AI is thinking...</p>';
        conversationView.appendChild(thinkingMsgDiv);
        conversationView.scrollTop = conversationView.scrollHeight;

        const allHistory = loadMessages();
        const recentHistoryForLLM = allHistory.slice(-(MAX_HISTORY_TURNS * 2)).map(msg => ({ role: msg.sender === 'user' ? 'user' : 'assistant', content: msg.text }));
        try {
            const response = await fetch('/chat', { method: 'POST', headers: { 'Content-Type': 'application/json', }, body: JSON.stringify({ query: query, conversation_history: recentHistoryForLLM }), });
            if (conversationView.contains(thinkingMsgDiv)) conversationView.removeChild(thinkingMsgDiv); 
            if (!response.ok) { const errData = await response.json(); addMessage(`Error: ${errData.error || response.statusText}`, 'ai', null, null, true, `error_${Date.now()}`, query); return; }
            const data = await response.json();
            addMessage(data.answer, 'ai', data.chart, data.raw_table, true, data.id, query); 
        } catch (error) { 
            if (conversationView.contains(thinkingMsgDiv)) conversationView.removeChild(thinkingMsgDiv);
            console.error('Failed to send message:', error);
            addMessage('Sorry, an error occurred while trying to reach the assistant.', 'ai', null, null, true, `error_${Date.now()}`, query);
        }
    }
    sendButton.addEventListener('click', handleUserQuery);
    userInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleUserQuery(); });
});