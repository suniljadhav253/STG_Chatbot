// app/static/js/insights.js
document.addEventListener('DOMContentLoaded', () => {
    const chartsContainer = document.getElementById('charts-container');
    const workplaceSelect = document.getElementById('hub-workplace-select');
    const newWorkplaceNameInput = document.getElementById('new-hub-workplace-name');
    const createWorkplaceBtn = document.getElementById('create-hub-workplace-btn');
    const deleteWorkplaceBtn = document.getElementById('delete-selected-workplace-btn');
    const currentWorkplaceTitle = document.getElementById('current-workplace-title');
    const ACTIVE_WORKPLACE_ID_KEY = 'rxoLogisticsActiveWorkplaceId';

    async function fetchWorkplaces() {
        try {
            const response = await fetch('/api/workplaces');
            if (!response.ok) throw new Error('Failed to fetch workplaces');
            return await response.json();
        } catch (error) {
            console.error("Error fetching workplaces:", error);
            // alert("Could not load workplaces."); // Avoid alert if not critical
            return [];
        }
    }

    async function populateWorkplaceSelect() {
        const workplaces = await fetchWorkplaces();
        workplaceSelect.innerHTML = ''; 
        let activeWorkplaceId = localStorage.getItem(ACTIVE_WORKPLACE_ID_KEY);
        let foundActive = false;

        if (workplaces.length === 0) {
            const option = document.createElement('option');
            option.value = "";
            option.textContent = "No workplaces. Create one!";
            workplaceSelect.appendChild(option);
            currentWorkplaceTitle.textContent = "No Workplace Selected";
            chartsContainer.innerHTML = '<p>Create or select a workplace to view insights.</p>';
            deleteWorkplaceBtn.disabled = true;
        } else {
            workplaces.forEach(wp => {
                const option = document.createElement('option');
                option.value = wp.id;
                option.textContent = wp.name;
                workplaceSelect.appendChild(option);
                if (wp.id === activeWorkplaceId) {
                    foundActive = true;
                }
            });
            
            if (foundActive && activeWorkplaceId) {
                workplaceSelect.value = activeWorkplaceId;
            } else if (workplaces.length > 0) { // Default to first if active not found or not set
                activeWorkplaceId = workplaces[0].id;
                workplaceSelect.value = activeWorkplaceId;
                localStorage.setItem(ACTIVE_WORKPLACE_ID_KEY, activeWorkplaceId);
            }
            
            if (workplaceSelect.value) {
                loadInsightsForWorkplace(workplaceSelect.value);
            }
            deleteWorkplaceBtn.disabled = workplaces.length <= 1 && workplaces[0].id.startsWith("default_wp_"); // Disable if only default left
        }
    }

    createWorkplaceBtn.addEventListener('click', async () => {
        const name = newWorkplaceNameInput.value.trim();
        if (!name) {
            alert("Please enter a name for the new workplace.");
            return;
        }
        try {
            const response = await fetch('/api/workplaces', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name })
            });
            const result = await response.json();
            if (!response.ok) {
                alert(`Error creating workplace: ${result.error || 'Unknown error'}`);
            } else {
                alert(`Workplace '${name}' created successfully!`);
                newWorkplaceNameInput.value = '';
                await populateWorkplaceSelect(); 
                workplaceSelect.value = result.id; 
                localStorage.setItem(ACTIVE_WORKPLACE_ID_KEY, result.id);
                loadInsightsForWorkplace(result.id); 
            }
        } catch (error) {
            alert(`Failed to create workplace: ${error}`);
        }
    });

    deleteWorkplaceBtn.addEventListener('click', async () => {
        const selectedWorkplaceId = workplaceSelect.value;
        if (!selectedWorkplaceId) {
            alert("Please select a workplace to delete.");
            return;
        }
        const selectedWorkplaceName = workplaceSelect.options[workplaceSelect.selectedIndex].text;
        if (confirm(`Are you sure you want to delete the workplace "${selectedWorkplaceName}" and all its insights? This cannot be undone.`)) {
            try {
                const response = await fetch(`/api/workplaces/${selectedWorkplaceId}`, { method: 'DELETE' });
                const result = await response.json();
                 if (!response.ok) {
                    alert(`Error deleting workplace: ${result.error || 'Unknown error'}`);
                } else {
                    alert(result.message);
                    localStorage.removeItem(ACTIVE_WORKPLACE_ID_KEY); // Clear active if deleted
                    await populateWorkplaceSelect(); 
                }
            } catch (error) {
                alert(`Failed to delete workplace: ${error}`);
            }
        }
    });


    workplaceSelect.addEventListener('change', () => {
        const selectedWorkplaceId = workplaceSelect.value;
        if (selectedWorkplaceId) {
            localStorage.setItem(ACTIVE_WORKPLACE_ID_KEY, selectedWorkplaceId);
            loadInsightsForWorkplace(selectedWorkplaceId);
        } else {
            currentWorkplaceTitle.textContent = "No Workplace Selected";
            chartsContainer.innerHTML = '<p>Select a workplace to view insights.</p>';
        }
    });

    async function loadInsightsForWorkplace(workplaceId) {
        const selectedWorkplaceOption = Array.from(workplaceSelect.options).find(opt => opt.value === workplaceId);
        const selectedWorkplaceName = selectedWorkplaceOption ? selectedWorkplaceOption.text : "Selected Workplace";
        
        currentWorkplaceTitle.textContent = `Insights in: ${selectedWorkplaceName}`;
        chartsContainer.innerHTML = '<p>Loading insights...</p>';
        try {
            const response = await fetch(`/api/workplaces/${workplaceId}/insights`);
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.error || 'Failed to load insights');
            }
            const insights = await response.json();

            if (!insights || insights.length === 0) {
                chartsContainer.innerHTML = '<p>No insights saved in this workplace yet. Go to the Chat Assistant to generate and save some!</p>';
                return;
            }
            chartsContainer.innerHTML = ''; 

            insights.forEach(insight => {
                const card = document.createElement('div');
                card.classList.add('insight-card');
                
                const queryTitle = document.createElement('h3');
                queryTitle.classList.add('insight-query-title');
                queryTitle.textContent = `Original Query: "${insight.query}"`;
                card.appendChild(queryTitle);

                // The 'summary' is the textual explanation/title from the chat
                if (insight.summary) {
                    const summaryP = document.createElement('p');
                    summaryP.classList.add('insight-summary-text');
                    summaryP.textContent = insight.summary; 
                    card.appendChild(summaryP);
                }

                const timestamp = document.createElement('p');
                timestamp.classList.add('insight-timestamp');
                timestamp.textContent = `Saved: ${new Date(insight.timestamp).toLocaleString()}`;
                card.appendChild(timestamp);

                if (insight.type && insight.type !== 'table' && insight.type !== 'text' && insight.data && insight.data.datasets) {
                    const chartWrapper = document.createElement('div');
                    chartWrapper.classList.add('insight-chart-wrapper');
                    const chartCanvas = document.createElement('canvas');
                    chartWrapper.appendChild(chartCanvas);
                    card.appendChild(chartWrapper);

                    if (typeof Chart !== 'undefined') {
                        try {
                            // Use saved options, including title and legend settings
                            new Chart(chartCanvas, { 
                                type: insight.type, 
                                data: insight.data, 
                                options: insight.options || { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: true }, title: {display: true, text: insight.summary || insight.query}}} 
                            });
                        } catch (e) { 
                            console.error("Error rendering insight chart:", e, insight);
                            const errorP = document.createElement('p'); errorP.textContent = "[Chart error]"; errorP.style.color='red';
                            chartWrapper.appendChild(errorP);
                        }
                    } else { /* Chart.js missing */ }
                } else if (insight.type === 'table' && insight.data && insight.data.headers && insight.data.rows) { 
                    const tableContainer = document.createElement('div');
                    tableContainer.classList.add('table-container');
                    const table = document.createElement('table'); /* ... table rendering ... */ 
                    const thead = document.createElement('thead'); const tbody = document.createElement('tbody'); const headerRow = document.createElement('tr');
                    insight.data.headers.forEach(h => {const th=document.createElement('th'); th.textContent=h; headerRow.appendChild(th);});
                    thead.appendChild(headerRow); table.appendChild(thead);
                    insight.data.rows.forEach(rD => {const r=document.createElement('tr'); rD.forEach(cD => {const td=document.createElement('td'); td.textContent=cD; r.appendChild(td);}); tbody.appendChild(r);});
                    table.appendChild(tbody); tableContainer.appendChild(table); card.appendChild(tableContainer);
                }
                
                const actionsDiv = document.createElement('div');
                actionsDiv.classList.add('actionsDiv'); // Class for styling
                const deleteInsightBtn = document.createElement('button');
                deleteInsightBtn.textContent = 'Remove Insight';
                deleteInsightBtn.onclick = async () => {
                    if (confirm(`Remove this insight (Query: "${insight.query}") from "${selectedWorkplaceName}"?`)) {
                        try {
                            const delResponse = await fetch(`/api/workplaces/${workplaceId}/insights/${insight.id}`, { method: 'DELETE' });
                            const delResult = await delResponse.json();
                            if (delResponse.ok) { loadInsightsForWorkplace(workplaceId); } 
                            else { alert(`Error removing insight: ${delResult.error}`); }
                        } catch (err) { alert(`Failed to remove insight: ${err}`); }
                    }
                };
                actionsDiv.appendChild(deleteInsightBtn);
                card.appendChild(actionsDiv);
                chartsContainer.appendChild(card);
            });

        } catch (error) {
            chartsContainer.innerHTML = `<p>Could not load insights for ${selectedWorkplaceName}: ${error.message}</p>`;
            console.error('Error in loadInsightsForWorkplace:', error);
        }
    }
    populateWorkplaceSelect();
});