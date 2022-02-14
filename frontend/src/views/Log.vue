<template>
  <div>
    <el-table
      :data="
        logFiles.slice((currentPage - 1) * pagesize, currentPage * pagesize)
      "
      stripe
      style="width: 100%"
      :default-sort="{ prop: 'create_time', order: 'descending' }"
      :current-change.sync="currentPage"
    >
      <el-table-column fixed prop="lid" label="ID" sortable width="60">
      </el-table-column>
      <el-table-column sortable prop="filename" :label="$t('log.filename')">
      </el-table-column>
      <el-table-column
        sortable
        prop="room_id"
        :label="$t('log.roomId')"
        width="120"
      >
      </el-table-column>
      <el-table-column
        sortable
        prop="create_time"
        :label="$t('log.createTime')"
        width="200"
      >
        <template slot-scope="scope">{{ scope.row.create_time }}</template>
      </el-table-column>
      <el-table-column fixed="right" :label="$t('log.actions')" width="200">
        <template slot-scope="scope">
          <el-button
            @click="handlePreview(scope.row)"
            type="primary"
            size="mini"
            icon="el-icon-search"
            circle
          ></el-button>
          <el-button
            @click="handleDownload(scope.row)"
            type="success"
            size="mini"
            circle
            icon="el-icon-download"
          ></el-button>
          <el-button
            type="danger"
            size="mini"
            icon="el-icon-delete"
            circle
          ></el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      @size-change="handleSizeChange"
      @current-change="handleCurrentChange"
      :page-sizes="[10, 15, 20]"
      :page-size="pagesize"
      layout="total, sizes, prev, pager, next, jumper"
      :total="total"
    >
    </el-pagination>
    <el-drawer
      :title="currentPreviewFile"
      :visible.sync="showDrawer"
      direction="rtl"
      size="30%"
    >
      <el-card class="preview-card">
        <div
          v-if="!currentPreviewContent || currentPreviewContent.length === 0"
        >
          {{ $t("log.nothing") }}
        </div>
        <div v-for="(item, i) in currentPreviewContent" :key="`dm-${i}`">
          {{ item }}
        </div>
      </el-card>
    </el-drawer>
  </div>
</template>

<script>
import axios from "axios";
// import Room from "./Room.vue";
// const exampleLogFileData = [
//   {
//     lid: 1,
//     filename: "2022-02-14-04-56-39.log",
//     room_id: 114514,
//     create_time: new Date(1644715917000),
//   },
//   {
//     lid: 2,
//     filename: "2022-02-14-04-56-39.log",
//     room_id: 114514,
//     create_time: new Date(1644615917000),
//   },
//   {
//     lid: 3,
//     filename: "2022-02-14-04-56-39.log",
//     room_id: 114514,
//     create_time: new Date(1644515917000),
//   },
//   {
//     lid: 4,
//     filename: "2022-02-14-04-56-39.log",
//     room_id: 114515,
//     create_time: new Date(1644415917000),
//   },
//   {
//     lid: 5,
//     filename: "2022-02-14-04-56-39.log",
//     room_id: 114515,
//     create_time: new Date(1644315917000),
//   },
// ];
// const exampleDanmakuData = [
//   {
//     cmd: 2,
//     data: [
//       "//i2.hdslb.com/bfs/face/cdde8a13b239a74c33a024382ea1045fa86a09a0.jpg@48w_48h",
//       1644788643,
//       "\u8bfa\u62c9Noella",
//       3,
//       "24",
//       0,
//       0,
//       13,
//       0,
//       1,
//       0,
//       "f955303491524be88f4a6b85a7ad0cc2",
//       "",
//     ],
//   },
//   {
//     cmd: 2,
//     data: [
//       "//i2.hdslb.com/bfs/face/cdde8a13b239a74c33a024382ea1045fa86a09a0.jpg@48w_48h",
//       1644788643,
//       "\u8bfa\u62c9Noella",
//       3,
//       "23",
//       0,
//       0,
//       13,
//       0,
//       1,
//       0,
//       "f955303491524be88f4a6b85a7ad0cc2",
//       "",
//     ],
//   },
//   {
//     cmd: 2,
//     data: [
//       "//i2.hdslb.com/bfs/face/cdde8a13b239a74c33a024382ea1045fa86a09a0.jpg@48w_48h",
//       1644788643,
//       "\u8bfa\u62c9Noella",
//       3,
//       "22",
//       0,
//       0,
//       13,
//       0,
//       1,
//       0,
//       "f955303491524be88f4a6b85a7ad0cc2",
//       "",
//     ],
//   },
//   {
//     cmd: 2,
//     data: [
//       "//i2.hdslb.com/bfs/face/cdde8a13b239a74c33a024382ea1045fa86a09a0.jpg@48w_48h",
//       1644788643,
//       "\u8bfa\u62c9Noella",
//       3,
//       "21",
//       0,
//       0,
//       13,
//       0,
//       1,
//       0,
//       "f955303491524be88f4a6b85a7ad0cc2",
//       "",
//     ],
//   },
// ];
export default {
  // components: { Room },
  data() {
    return {
      logFiles: [],
      danmakus: [],
      showDrawer: false,
      currentPreviewFile: "",
      currentPreviewContent: [],
      currentPage: 1,
      pagesize: 10,
      total: 0,
    };
  },
  methods: {
    handleSizeChange(val) {
      this.pagesize = val;
    },
    handleCurrentChange(val) {
      this.currentPage = val;
    },
    async handleDownload(row) {
      window.open(`/api/log?lid=${row.lid}&op=download`);
    },
    formatTime(d) {
      return d.toLocaleString();
    },
    async handlePreview(row) {
      this.showDrawer = true;
      this.currentPreviewFile = row.filename;
      const res = await axios.get("/api/log", {
        params: {
          lid: row.lid,
          op: "view",
        },
      });
      console.log(res.data);
      this.currentPreviewContent = res.data.data;
      this.currentPreviewContent.forEach((v, i) => {
        this.currentPreviewContent[i] = JSON.parse(v);
        this.currentPreviewContent[i].content = JSON.parse(
          this.currentPreviewContent[i].content
        );
        this.currentPreviewContent[i] = JSON.stringify(
          this.currentPreviewContent[i]
        );
      });
    },
    async handleDelete(row) {
      const res = await axios.get("/api/log", {
        params: {
          lid: row.lid,
          op: "view",
        },
      });
      console.log(res.data);
      this.currentPreviewContent = res.data.data;
      this.currentPreviewContent.forEach((v, i) => {
        this.currentPreviewContent[i] = JSON.parse(v);
        this.currentPreviewContent[i].content = JSON.parse(
          this.currentPreviewContent[i].content
        );
        this.currentPreviewContent[i] = JSON.stringify(
          this.currentPreviewContent[i]
        );
      });
    },
  },
  async mounted() {
    // get all logs
    await axios
      .get("/api/log")
      .catch(() => {
        this.$message.error("Cannot fetch log files");
      })
      .then((res) => {
        console.log(res);
        this.logFiles = JSON.parse(res.data.data);
        console.log(this.logFiles);
        this.total = this.logFiles.length;
      });
  },
};
</script>

<style lang="css" scoped>
#fakebody {
  outline: 1px #999 dashed;
  height: 100%;
}
.preview-card {
  width: calc(100% - 40px);
  margin-left: 20px;
  padding: 5px;
  word-break: break-all;
  font-family: monospace;
}
.preview-card div:nth-child(even) {
  margin: 5px 0;
  border-radius: 4px;
  padding: 10px;
  background-color: rgba(114, 164, 216, 0.153);
}
</style>
