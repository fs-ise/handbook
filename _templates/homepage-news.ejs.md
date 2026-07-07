```{=html}
<div class="homepage-news-items">
<% for (const item of items) { %>
  <div class="news-item">
    <div class="news-date"><%- item.date %></div>
    <div class="news-content">
      <a class="news-title" href="<%- item.path %>"><%- item.title %></a>
      <% if (item.description) { %>
      <div class="news-description"><%- item.description %></div>
      <% } %>
    </div>
  </div>
<% } %>
</div>
```